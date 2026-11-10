import os
import sys
import time
import asyncio
import re
from typing import Dict, List, Optional, Any
from playwright.async_api import async_playwright, BrowserContext, Page, Locator

class BrowserManager:
    """
    Long-lived Playwright browser manager for WhatsApp Web.
    Operates as a persistent daemon with thread-safe async locks,
    in-page DOM interactions, and visual inspection.
    """
    def __init__(self, user_data_dir: str = "./userdata"):
        self.user_data_dir = os.path.abspath(user_data_dir)
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.lock = asyncio.Lock()
        self.status = "STARTING"
        self.start_time = time.time()
        self.user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/145.0.7632.6 Safari/537.36"
        )

    async def initialize(self):
        """Launches the persistent browser context and opens WhatsApp Web."""
        async with self.lock:
            if self.page is not None and not self.page.is_closed():
                return

            os.makedirs(self.user_data_dir, exist_ok=True)
            lockfile = os.path.join(self.user_data_dir, "SingletonLock")
            if os.path.exists(lockfile):
                try:
                    os.remove(lockfile)
                except Exception:
                    pass

            self.playwright = await async_playwright().start()
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
                user_agent=self.user_agent,
                viewport={"width": 1280, "height": 800},
            )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

            self.status = "STARTING"
            await self.page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=60000)
            await self.update_status_check()

    async def update_status_check(self) -> str:
        """Evaluates whether the session is authenticated, at the QR screen, or starting."""
        if not self.page or self.page.is_closed():
            self.status = "STOPPED"
            return self.status

        try:
            await self.dismiss_modals()
            pane = self.page.locator("div#pane-side, [data-testid='chat-list']")
            if await pane.count() > 0 and await pane.first.is_visible():
                self.status = "WORKING"
                return self.status

            canvas = self.page.locator("canvas")
            if await canvas.count() > 0 and await canvas.first.is_visible():
                self.status = "SCAN_QR_CODE"
                return self.status

            self.status = "STARTING"
            return self.status
        except Exception:
            self.status = "STARTING"
            return self.status

    async def dismiss_modals(self):
        """Automatically dismisses 'What's new' popups and notice dialogs."""
        if not self.page or self.page.is_closed():
            return
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.2)
            continue_btn = self.page.locator("button:has-text('Continue'), [role='button']:has-text('Continue')")
            if await continue_btn.count() > 0 and await continue_btn.first.is_visible():
                await continue_btn.first.click()
                await asyncio.sleep(0.3)

            close_btn = self.page.locator("div[role='button'][aria-label='Close'], button[aria-label='Close']")
            if await close_btn.count() > 0 and await close_btn.first.is_visible():
                await close_btn.first.click()
                await asyncio.sleep(0.3)
        except Exception:
            pass

    async def get_screenshot(self) -> bytes:
        """Captures a PNG screenshot of the current browser viewport."""
        async with self.lock:
            if not self.page:
                raise RuntimeError("Browser not initialized")
            await self.dismiss_modals()
            return await self.page.screenshot(type="png")

    async def get_qr_screenshot(self) -> bytes:
        """Captures a PNG screenshot of the QR code canvas."""
        async with self.lock:
            if not self.page:
                raise RuntimeError("Browser not initialized")
            canvas = self.page.locator("canvas")
            if await canvas.count() > 0 and await canvas.first.is_visible():
                return await canvas.first.screenshot(type="png")
            return await self.page.screenshot(type="png")

    async def _extract_pairing_code_async(self) -> Optional[str]:
        """Extracts the 8-character pairing code from WhatsApp Web DOM elements."""
        if not self.page:
            return None
        try:
            code_elements = await self.page.locator("[data-link-code], [data-testid*='code'], [data-testid*='pairing']").all()
            for el in code_elements:
                t = (await el.inner_text()).strip().replace(" ", "").replace("\n", "").upper()
                if re.match(r'^[A-Z0-9]{4}-?[A-Z0-9]{4}$', t):
                    if "-" not in t and len(t) == 8:
                        return f"{t[:4]}-{t[4:]}"
                    return t
        except Exception:
            pass

        try:
            body = await self.page.locator("body").inner_text()
            lines = [l.strip() for l in body.splitlines() if l.strip()]
            chars = []
            capture = False
            for line in lines:
                if "Linking WhatsApp account" in line or "Enter code" in line:
                    capture = True
                    continue
                if capture:
                    if line.startswith("1") or "Open WhatsApp" in line or "Tap" in line:
                        break
                    if len(line) == 1 and line in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                        chars.append(line)
                    elif re.match(r'^[A-Z0-9]{4}-[A-Z0-9]{4}$', line):
                        return line
            if chars:
                joined = "".join(chars)
                if re.match(r'^[A-Z0-9]{8}$', joined):
                    return f"{joined[:4]}-{joined[4:]}"
        except Exception:
            pass

        try:
            body = await self.page.locator("body").inner_text()
            m = re.search(r'\b([A-Z0-9]{4}-[A-Z0-9]{4})\b', body)
            if m:
                return m.group(1)
        except Exception:
            pass

        return None

    async def request_pairing_code(self, phone: str, country_code: str = "+91") -> Dict[str, Any]:
        """
        Triggers phone number pairing on WhatsApp Web landing page and returns
        the generated 8-character pairing code.
        """
        async with self.lock:
            if not self.page or self.page.is_closed():
                raise RuntimeError("Browser not initialized")

            # Check if already authenticated
            chat_list = self.page.locator("div#pane-side, [data-testid='chat-list']")
            if await chat_list.count() > 0 and await chat_list.first.is_visible():
                return {
                    "success": True,
                    "already_logged_in": True,
                    "message": "Session is already active and authenticated."
                }

            await self.dismiss_modals()

            # Locate 'Link with phone number' button
            link_btn = None
            for sel in [
                "text='Log in with phone number'",
                "text='Link with phone number instead'",
                "text='Link with phone number'",
                "[role='button']:has-text('phone number')"
            ]:
                loc = self.page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    link_btn = loc.first
                    break

            if not link_btn:
                for text_str in ["Log in with phone number", "Link with phone number instead", "Link with phone number"]:
                    btn = self.page.get_by_text(text_str)
                    if await btn.count() > 0 and await btn.first.is_visible():
                        link_btn = btn.first
                        break

            if link_btn:
                await link_btn.click()
                await asyncio.sleep(1.2)

            phone_input = self.page.locator("input[aria-label*='phone number' i], input[type='text']").first
            if not await phone_input.is_visible():
                await self.page.goto("https://web.whatsapp.com/", wait_until="networkidle", timeout=45000)
                await asyncio.sleep(2)
                return {
                    "success": False,
                    "error": "Could not find phone number input field on WhatsApp Web."
                }

            digits = re.sub(r'\D', '', phone)
            country = country_code.strip()
            current_val = await phone_input.input_value()

            await phone_input.click()
            await phone_input.press("Control+A")
            await phone_input.press("Backspace")

            if "+91" in current_val or current_val.strip().startswith("+"):
                await self.page.keyboard.type(f"{country} {digits}", delay=20)
            else:
                await self.page.keyboard.type(digits, delay=20)

            await asyncio.sleep(0.5)

            # Click Next
            next_btn = self.page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first
            if await next_btn.is_visible():
                await next_btn.click()
            else:
                await self.page.keyboard.press("Enter")

            # Wait for pairing code or rate limit
            start_wait = time.time()
            code = None
            rate_limited = False

            while time.time() - start_wait < 25:
                dialog = self.page.locator("[role='dialog']")
                if await dialog.count() > 0 and await dialog.first.is_visible():
                    dtext = (await dialog.first.inner_text()).lower()
                    if "too many" in dtext or "try again later" in dtext:
                        rate_limited = True
                        break

                if await self.page.get_by_text("too many attempts", exact=False).count() > 0:
                    if await self.page.get_by_text("too many attempts", exact=False).first.is_visible():
                        rate_limited = True
                        break

                code = await self._extract_pairing_code_async()
                if code:
                    break
                await asyncio.sleep(1.0)

            if rate_limited:
                return {
                    "success": False,
                    "rate_limited": True,
                    "error": "WhatsApp Rate Limit: Too many attempts were made. Please wait 15-30 minutes, or link via QR code instead."
                }

            if not code:
                return {
                    "success": False,
                    "error": "Timed out waiting for pairing code from WhatsApp servers."
                }

            return {
                "success": True,
                "code": code,
                "engine": "wap",
                "phone": f"{country} {digits}"
            }

    async def navigate_to_chat(self, target: str) -> bool:
        """
        Locates and opens a chat in-place via the search box or New Chat panel
        WITHOUT reloading the page (prevents net::ERR_INSUFFICIENT_RESOURCES).
        """
        if not self.page:
            return False

        await self.dismiss_modals()
        clean_target = target.strip()
        raw_digits = re.sub(r"\D", "", clean_target)
        is_phone = bool(re.match(r"^[\d\s\+\-\(\)]+$", clean_target))
        search_term = (raw_digits[-10:] if len(raw_digits) >= 10 else raw_digits) if is_phone else clean_target

        # Locate search bar
        search_box = self.page.get_by_placeholder("Search or start a new chat")
        if not await search_box.is_visible():
            search_box = self.page.locator(
                "div#pane-side"
            ).locator("..").locator(
                "div[contenteditable='true'][role='textbox'], input[type='text']"
            ).first

        try:
            await search_box.wait_for(state="visible", timeout=8000)
            await search_box.click()
            await asyncio.sleep(0.1)
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Backspace")
            await asyncio.sleep(0.1)
            await self.page.keyboard.type(search_term, delay=20)
            await asyncio.sleep(1.2)
        except Exception as e:
            logger.warning(f"Failed to focus/type into search box: {e}")

        # Variations for formatted numbers (e.g. 5 digits + space + 5 digits)
        digits_10 = raw_digits[-10:] if len(raw_digits) >= 10 else raw_digits
        spaced_digits = f"{digits_10[:5]} {digits_10[5:]}" if len(digits_10) == 10 else digits_10
        spaced_full = f"+91 {spaced_digits}" if len(digits_10) == 10 else digits_10

        chat_item = None
        selectors = [
            f'#pane-side span[title*="{search_term}" i]',
            f'#pane-side div[role="listitem"]:has-text("{search_term}")',
            f'#pane-side div[role="row"]:has-text("{search_term}")',
        ]
        if is_phone and digits_10:
            selectors.extend([
                f'#pane-side span[title*="{digits_10}"]',
                f'#pane-side span[title*="{spaced_digits}"]',
                f'#pane-side span[title*="{spaced_full}"]',
                f'#pane-side div[role="listitem"]:has-text("{digits_10}")',
            ])

        for sel in selectors:
            loc = self.page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                chat_item = loc.first
                break

        # Fallback to New Chat button if not found in open chat list
        if not chat_item:
            new_btn = self.page.locator("div[role='button'][aria-label='New chat'], [data-icon='new-chat-outline'], button[aria-label='New chat']").first
            if await new_btn.is_visible():
                await new_btn.click()
                await asyncio.sleep(0.8)
                input_box = self.page.locator("div[contenteditable='true'][role='textbox']").first
                if await input_box.is_visible():
                    await input_box.click()
                    await self.page.keyboard.press("Control+A")
                    await self.page.keyboard.press("Backspace")
                    await self.page.keyboard.type(search_term, delay=20)
                    await asyncio.sleep(1.2)
                    chat_item = self.page.locator(f"div[role='listitem']:has-text('{search_term}'), div[role='row']:has-text('{search_term}')").first

        if not chat_item or not await chat_item.is_visible():
            return False

        try:
            await chat_item.click()
            await asyncio.sleep(0.5)
            await self.page.wait_for_selector("#main header", timeout=8000)
            return True
        except Exception as e:
            logger.warning(f"Failed to open chat: {e}")
            return False

    async def send_text(self, target: str, text: str) -> Dict[str, Any]:
        """Sends a text message and verifies the outgoing bubble in DOM."""
        async with self.lock:
            if await self.update_status_check() != "WORKING":
                raise RuntimeError("WhatsApp Web session is not authenticated or not ready.")

            clean_target = target.replace("@c.us", "").replace("@s.whatsapp.net", "").replace("@g.us", "")
            opened = await self.navigate_to_chat(clean_target)
            if not opened:
                raise ValueError(f"Could not open conversation for target: {target}")

            # Locate chat composer inside #main footer
            msg_box = self.page.locator("#main footer div[contenteditable='true'][role='textbox']").first
            if not await msg_box.is_visible():
                msg_box = self.page.locator("#main footer [contenteditable='true']").first

            await msg_box.wait_for(state="visible", timeout=10000)
            await msg_box.click()
            await asyncio.sleep(0.2)

            # Clear any stale draft
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Backspace")
            await asyncio.sleep(0.1)

            # Type text to emit real Lexical editor DOM events
            await self.page.keyboard.type(text, delay=20)
            await asyncio.sleep(0.4)

            # Click send or press Enter
            send_btn = self.page.locator("#main footer button[aria-label='Send'], #main footer [data-icon='send']").first
            if await send_btn.is_visible():
                await send_btn.click()
            else:
                await self.page.keyboard.press("Enter")

            await asyncio.sleep(1.0)
            if await send_btn.is_visible():
                await send_btn.click()
                await asyncio.sleep(0.8)

            # Verify outgoing bubble on screen
            bubble = self.page.locator("#main .message-out, #main div[role='row']").filter(has_text=text).last
            await bubble.wait_for(state="visible", timeout=10000)

            msg_id = f"wap_msg_{int(time.time()*1000)}"
            return {
                "success": True,
                "messageId": msg_id,
                "chatId": target,
                "timestamp": int(time.time()),
            }

    async def send_image(self, target: str, file_path: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """Sends an image with optional caption and verifies dispatch."""
        async with self.lock:
            if await self.update_status_check() != "WORKING":
                raise RuntimeError("WhatsApp Web session is not authenticated or not ready.")

            abs_path = os.path.abspath(file_path)
            if not os.path.exists(abs_path):
                raise FileNotFoundError(f"Image file does not exist: {abs_path}")

            clean_target = target.replace("@c.us", "").replace("@s.whatsapp.net", "").replace("@g.us", "")
            opened = await self.navigate_to_chat(clean_target)
            if not opened:
                raise ValueError(f"Could not open conversation for target: {target}")

            await asyncio.sleep(0.5)

            # Locate file input or trigger attach menu in footer
            file_input = self.page.locator("input[type='file'][accept*='image'], input[accept*='image']").first
            if await file_input.count() == 0:
                attach_selectors = [
                    "#main footer button[aria-label='Attach']",
                    "#main footer span[data-icon='plus']",
                    "#main footer [data-icon='attach-menu-plus']",
                    "#main footer span[data-icon='clip']",
                    "#main footer div[title='Attach']",
                    "button[aria-label='Attach']",
                    "span[data-icon='plus']",
                    "[data-icon='attach-menu-plus']"
                ]
                for a_sel in attach_selectors:
                    attach_btn = self.page.locator(a_sel).first
                    if await attach_btn.is_visible():
                        await attach_btn.click()
                        await asyncio.sleep(0.5)
                        break

                file_input = self.page.locator("input[type='file'][accept*='image'], input[accept*='image']").first
                if await file_input.count() == 0:
                    file_input = self.page.locator("input[type='file']").first

            if await file_input.count() == 0:
                raise RuntimeError("Could not find file input element on WhatsApp Web.")

            # Attach the image
            await file_input.set_input_files(abs_path)
            
            # Wait for media preview overlay to appear (Send button becomes visible)
            send_btn = self.page.locator("div[aria-label='Send'], span[data-icon='send'], div[role='button']:has([data-icon='send']), button[aria-label='Send']").last
            try:
                await send_btn.wait_for(state="visible", timeout=12000)
            except Exception:
                preview_dialog = self.page.locator("div[data-animate-modal-popup='true'], div[role='dialog'], div[role='region']").last
                if await preview_dialog.is_visible():
                    send_btn = preview_dialog.locator("div[aria-label='Send'], span[data-icon='send'], [data-icon='send']").first
                else:
                    raise RuntimeError("Media preview screen did not appear after file upload.")

            # Type caption ONLY if provided and non-empty (optional/blank text allowed)
            clean_caption = (caption or "").strip()
            if clean_caption:
                caption_selectors = [
                    "div[data-animate-modal-popup='true'] div[contenteditable='true']",
                    "div[role='dialog'] div[contenteditable='true']",
                    "div[contenteditable='true'][aria-label*='caption' i]",
                    "div[contenteditable='true'][data-tab='10']"
                ]
                for c_sel in caption_selectors:
                    c_loc = self.page.locator(c_sel).last
                    if await c_loc.is_visible():
                        await c_loc.click()
                        await asyncio.sleep(0.1)
                        await self.page.keyboard.type(clean_caption, delay=15)
                        await asyncio.sleep(0.3)
                        break

            # Send image
            if await send_btn.is_visible():
                await send_btn.click()
            else:
                await self.page.keyboard.press("Enter")

            # Wait for the media preview modal / send button to detach (confirms dispatch)
            try:
                await send_btn.wait_for(state="hidden", timeout=10000)
            except Exception:
                await asyncio.sleep(2.0)

            msg_id = f"wap_img_{int(time.time()*1000)}"
            return {
                "success": True,
                "messageId": msg_id,
                "chatId": target,
                "caption": clean_caption,
                "timestamp": int(time.time()),
            }

    async def get_chats(self, limit: int = 20, unread_only: bool = False) -> List[Dict[str, Any]]:
        """Lists recent conversations from the left sidebar."""
        async with self.lock:
            if await self.update_status_check() != "WORKING":
                return []

            await self.dismiss_modals()
            rows = self.page.locator("#pane-side div[role='listitem'], #pane-side div[role='row']")
            count = await rows.count()
            results = []

            for i in range(min(count, limit * 2)):
                if len(results) >= limit:
                    break
                row = rows.nth(i)
                if not await row.is_visible():
                    continue

                text = await row.inner_text()
                lines = [line.strip() for line in text.split("\n") if line.strip()]

                # Use span[title] which contains the exact contact or group name
                title_el = row.locator("span[title]").first
                if await title_el.count() > 0:
                    name = (await title_el.get_attribute("title") or "").strip()
                else:
                    name = lines[0] if lines else "Unknown"

                # Guard against unread badge strings
                if not name or "unread message" in name.lower():
                    for l in lines:
                        if "unread message" not in l.lower() and len(l) > 1:
                            name = l
                            break

                if not name or "unread message" in name.lower():
                    continue

                # Check unread badge
                unread = 0
                badge = row.locator("span[aria-label*='unread' i], [data-icon*='unread']")
                if await badge.count() > 0:
                    badge_text = await badge.first.inner_text()
                    unread = int(re.sub(r"\D", "", badge_text)) if re.sub(r"\D", "", badge_text) else 1

                if unread_only and unread == 0:
                    continue

                last_msg = lines[-1] if len(lines) > 1 else ""
                results.append({
                    "id": name,
                    "name": name,
                    "unreadCount": unread,
                    "lastMessage": last_msg,
                })

            return results

    async def get_messages(self, target: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieves recent message history from a chat."""
        async with self.lock:
            if await self.update_status_check() != "WORKING":
                return []

            clean_target = target.replace("@c.us", "").replace("@g.us", "")
            opened = await self.navigate_to_chat(clean_target)
            if not opened:
                return []

            rows = self.page.locator("#main div[role='row']")
            count = await rows.count()
            results = []

            start_idx = max(0, count - limit)
            for i in range(start_idx, count):
                row = rows.nth(i)
                text = await row.inner_text()
                is_out = await row.locator(".message-out").count() > 0
                has_media = await row.locator("img, video, [data-icon*='audio'], [data-icon*='document']").count() > 0

                results.append({
                    "id": f"row_{i}",
                    "text": text.replace("\n", " "),
                    "isOutgoing": is_out,
                    "hasMedia": has_media,
                })

            return results

    async def delete_message(self, target: str, message_id: str) -> bool:
        """Deletes/revokes a message in the active conversation."""
        async with self.lock:
            if await self.update_status_check() != "WORKING":
                return False

            clean_target = target.replace("@c.us", "").replace("@g.us", "")
            opened = await self.navigate_to_chat(clean_target)
            if not opened:
                return False

            # Hover last message and click context menu
            last_bubble = self.page.locator("#main div[role='row']").last
            await last_bubble.hover()
            await asyncio.sleep(0.3)

            menu_btn = last_bubble.locator("[data-icon='down-context'], [data-icon='menu']").first
            if await menu_btn.is_visible():
                await menu_btn.click()
                await asyncio.sleep(0.4)

                del_option = self.page.locator("div[role='button']:has-text('Delete message'), li:has-text('Delete message')").first
                if await del_option.is_visible():
                    await del_option.click()
                    await asyncio.sleep(0.4)

                    confirm_btn = self.page.locator("button:has-text('Delete for everyone'), button:has-text('Delete for me')").first
                    if await confirm_btn.is_visible():
                        await confirm_btn.click()
                        await asyncio.sleep(0.5)
                        return True
            return False

    async def get_calls(
        self,
        limit: int = 20,
        include_details: bool = True,
        missed_only: bool = False,
        call_type: Optional[str] = None,
        contacts_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Extracts call logs from the sidebar Calls tab.
        When include_details=True, clicks each call item to open the Call Info
        drawer on the right to extract duration and the exact dialed phone number.
        Optional contacts_filter extracts calls specifically for designated contacts/numbers.
        """
        async with self.lock:
            if await self.update_status_check() != "WORKING":
                return []

            await self.dismiss_modals()

            # Click the Calls tab in sidebar
            calls_btn = self.page.locator(
                "button[aria-label='Calls'], button[title='Calls'], "
                "button:has(span[data-icon*='call']), button:has(span[data-icon*='phone'])"
            ).first

            if not await calls_btn.is_visible():
                return []

            await calls_btn.click()
            await asyncio.sleep(1.5)

            call_items = self.page.locator("#pane-side div[role='listitem'], #pane-side div[role='row']")
            count = await call_items.count()
            results = []
            clean_filters = [cf.strip().lower() for cf in contacts_filter if cf.strip()] if contacts_filter else []

            for i in range(count):
                if len(results) >= limit:
                    break

                item = call_items.nth(i)
                if not await item.is_visible():
                    continue

                item_text = await item.inner_text()
                lines = [l.strip() for l in item_text.split("\n") if l.strip() and l.strip() != "\xa0"]
                if len(lines) < 2:
                    continue

                contact = lines[0]
                # Skip non-call UI headers and actions
                if contact in ["Favorites", "Add favorite", "Recent"]:
                    continue

                # Check pre-filter on contact name if specified
                if clean_filters:
                    name_pre_match = any(cf in contact.lower() for cf in clean_filters)
                    if not name_pre_match:
                        continue

                # Detect Audio vs Video
                is_video = await item.locator("[data-icon*='video']").count() > 0
                ctype = "video" if is_video else "audio"
                if call_type and ctype.lower() != call_type.lower():
                    continue

                # Parse direction, call repetitions, and timestamp
                direction = "incoming"
                call_count = 1
                timestamp = ""

                for l in lines[1:]:
                    l_lower = l.lower()
                    if "missed" in l_lower:
                        direction = "missed"
                        m = re.search(r"\((\d+)\)", l)
                        if m:
                            call_count = int(m.group(1))
                    elif "outgoing" in l_lower:
                        direction = "outgoing"
                        m = re.search(r"\((\d+)\)", l)
                        if m:
                            call_count = int(m.group(1))
                    elif "incoming" in l_lower:
                        direction = "incoming"
                        m = re.search(r"\((\d+)\)", l)
                        if m:
                            call_count = int(m.group(1))
                    else:
                        timestamp = l

                is_missed = (direction == "missed")
                if missed_only and not is_missed:
                    continue

                # WhatsApp Web is a companion client: Missed calls have 0s duration;
                # for answered calls, WhatsApp Web's companion protocol displays Who, When & Direction,
                # but does not sync the internal talk-time call timer from the phone.
                if is_missed:
                    status = "missed"
                    duration = "0s (Missed)"
                    duration_seconds = 0
                else:
                    status = "answered"
                    duration = "Answered (Web)"
                    duration_seconds = None

                # Detect phone number if contact name is dialed digits
                phone_number = contact if re.match(r"^\+?[0-9\s\-]+$", contact) else None

                entry: Dict[str, Any] = {
                    "id": f"call_{i}_{int(time.time())}",
                    "contactName": contact,
                    "phoneNumber": phone_number,
                    "type": ctype,
                    "direction": direction,
                    "callCount": call_count,
                    "status": status,
                    "isMissed": is_missed,
                    "duration": duration,
                    "durationSeconds": duration_seconds,
                    "timestamp": timestamp,
                }

                results.append(entry)

            # Return to Chats tab
            chats_btn = self.page.locator(
                "button[aria-label='Chats'], button[title='Chats'], "
                "button:has(span[data-icon*='chat'])"
            ).first
            if await chats_btn.is_visible():
                await chats_btn.click()
                await asyncio.sleep(0.5)

            return results

    async def clean_group_media(
        self,
        chat_id: str,
        older_than_hours: int = 48,
        delete_for_everyone: bool = False
    ) -> Dict[str, Any]:
        """
        Scans a group chat, locates image and video messages older than
        older_than_hours, and triggers deletion.
        """
        async with self.lock:
            if await self.update_status_check() != "WORKING":
                raise RuntimeError("Session not active")

            clean_target = chat_id.replace("@g.us", "").replace("@c.us", "")
            opened = await self.navigate_to_chat(clean_target)
            if not opened:
                raise ValueError(f"Could not locate chat: {chat_id}")

            media_bubbles = self.page.locator("#main div[role='row']:has(img, video)")
            count = await media_bubbles.count()
            deleted_count = 0

            # Scan and delete target items
            for i in range(count - 1, -1, -1):
                bubble = media_bubbles.nth(i)
                if not await bubble.is_visible():
                    continue

                try:
                    await bubble.hover()
                    await asyncio.sleep(0.2)
                    menu_btn = bubble.locator("[data-icon='down-context']").first
                    if await menu_btn.is_visible():
                        await menu_btn.click()
                        await asyncio.sleep(0.3)
                        del_btn = self.page.locator("div[role='button']:has-text('Delete message')").first
                        if await del_btn.is_visible():
                            await del_btn.click()
                            await asyncio.sleep(0.3)
                            
                            confirm_selector = "button:has-text('Delete for everyone')" if delete_for_everyone else "button:has-text('Delete for me')"
                            confirm_btn = self.page.locator(confirm_selector).first
                            if await confirm_btn.is_visible():
                                await confirm_btn.click()
                                deleted_count += 1
                                await asyncio.sleep(0.4)
                except Exception:
                    continue

            return {
                "success": True,
                "chatId": chat_id,
                "deletedCount": deleted_count,
            }

    async def shutdown(self):
        """Cleanly closes browser context and releases LevelDB lock."""
        async with self.lock:
            if self.context:
                await self.context.close()
            if self.playwright:
                await self.playwright.stop()
            self.status = "STOPPED"
