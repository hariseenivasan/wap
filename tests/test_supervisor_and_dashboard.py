"""
Unit tests for WAP Unified Dashboard, Login view, Configuration, and Supervisor Process Management APIs.
Ensures zero credential leakage and verifies API conformance.
"""

import pytest
import requests

BASE_URL = "http://127.0.0.1:3001"
FILESERVER_URL = "http://127.0.0.1:9002"

class TestDashboardAndSupervisorApi:

    def test_dashboard_page_retrieval(self):
        res = requests.get(f"{BASE_URL}/dashboard")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "WABot & WAP Control Center" in res.text
        assert "pane-wabot" in res.text

    def test_login_page_retrieval(self):
        res = requests.get(f"{BASE_URL}/login")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "WhatsApp Authentication Hub" in res.text

    def test_wabot_process_status(self):
        res = requests.get(f"{BASE_URL}/api/wabot/status")
        assert res.status_code == 200
        data = res.json()
        assert "statename" in data
        assert "pid" in data
        assert "uptimeSeconds" in data
        assert "engine" in data
        assert data.get("supervisorAvailable") is True

    def test_wabot_logs_retrieval(self):
        res = requests.get(f"{BASE_URL}/api/wabot/logs?bytes_count=1024")
        assert res.status_code == 200
        data = res.json()
        assert "stdout" in data
        assert "stderr" in data

    def test_config_retrieval_masks_credentials(self):
        res = requests.get(f"{BASE_URL}/api/config")
        assert res.status_code == 200
        data = res.json()
        assert "engine" in data
        if "phone_number" in data:
            assert data["phone_number"] == "***masked***"

    def test_config_update(self):
        res = requests.post(f"{BASE_URL}/api/config", json={
            "period_seconds": 600,
            "jitter_percentage": 15,
            "unread_label": "unread message"
        })
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") is True

    def test_qr_code_for_both_engines(self):
        # WAP engine QR
        res_wap = requests.get(f"{BASE_URL}/api/qr?engine=wap&format=image")
        assert res_wap.status_code == 200
        assert res_wap.headers.get("content-type") == "image/png"

        # WAHA engine QR
        res_waha = requests.get(f"{BASE_URL}/api/qr?engine=waha&format=image")
        assert res_waha.status_code in [200, 500]  # 200 when session started

    def test_port_9002_deprecated_redirects(self):
        # 9002 /linknumber/ must redirect to 3001 /login
        r1 = requests.get(f"{FILESERVER_URL}/linknumber/", allow_redirects=False)
        assert r1.status_code in [301, 302]
        assert "3001/login" in r1.headers.get("location", "")

        # 9002 /linkqr/ must redirect to 3001 /login
        r2 = requests.get(f"{FILESERVER_URL}/linkqr/", allow_redirects=False)
        assert r2.status_code in [301, 302]
        assert "3001/login" in r2.headers.get("location", "")

        # API status check indicates deprecation
        r3 = requests.get(f"{FILESERVER_URL}/api/status_linknumber")
        assert r3.status_code == 200
        assert r3.json().get("state") == "deprecated"

    def test_schedules_api_and_dashboard_integration(self):
        """Verify GET /api/schedules and sleek user-friendly schedules UI components (no gws.json leakage)."""
        # Check API response
        r = requests.get(f"{BASE_URL}/api/schedules")
        assert r.status_code == 200
        data = r.json()
        assert "schedules" in data
        assert isinstance(data["schedules"], list)
        assert "summary" in data

        # Check Dashboard HTML contains sleek schedule components
        dash_res = requests.get(f"{BASE_URL}/dashboard")
        assert dash_res.status_code == 200
        html = dash_res.text
        assert "pane-schedules" in html
        assert "btn-add-schedule" in html
        assert "schedule-modal" in html
        assert "sched-contact-name" in html
        assert "stat-schedules-contacts" in html

        # Strict check: gws.json is NEVER referenced or exposed in dashboard HTML
        assert "gws.json" not in html

        # Test granular schedule endpoints: add, edit, delete
        test_item = {
            "contact_name": "Test Client Alert",
            "message": "Testing automated notifications",
            "schedules": [
                {
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "type": "daily",
                    "jitter_percentage": 10
                }
            ]
        }
        # Add
        r_add = requests.post(f"{BASE_URL}/api/schedules/add", json=test_item)
        assert r_add.status_code == 200
        add_data = r_add.json()
        assert add_data["success"] is True
        idx = add_data["index"]

        # Edit
        test_item["message"] = "Updated automated notification text"
        r_edit = requests.put(f"{BASE_URL}/api/schedules/{idx}", json=test_item)
        assert r_edit.status_code == 200
        assert r_edit.json()["success"] is True

        # Delete
        r_del = requests.delete(f"{BASE_URL}/api/schedules/{idx}")
        assert r_del.status_code == 200
        assert r_del.json()["success"] is True

    def test_call_extraction_config_api(self):
        """Verify GET /api/config/call-extraction and POST /api/config/call-extraction."""
        # Read current
        r1 = requests.get(f"{BASE_URL}/api/config/call-extraction")
        assert r1.status_code == 200
        orig_data = r1.json()

        # Update
        test_payload = {
            "mode": "whitelist",
            "target_contacts": ["Test User A", "919999999999"]
        }
        r2 = requests.post(f"{BASE_URL}/api/config/call-extraction", json=test_payload)
        assert r2.status_code == 200
        assert r2.json().get("success") is True

        # Verify updated
        r3 = requests.get(f"{BASE_URL}/api/config/call-extraction")
        assert r3.status_code == 200
        data3 = r3.json()
        assert data3["filter_mode"] == "whitelist"
        assert "Test User A" in data3["target_contacts"]

        # Restore original
        restore_payload = {
            "mode": orig_data.get("filter_mode", "all"),
            "target_contacts": orig_data.get("target_contacts", [])
        }
        requests.post(f"{BASE_URL}/api/config/call-extraction", json=restore_payload)

    def test_dashboard_log_filtering_and_notice(self):
        """Verify log filter buttons and historical stderr disclaimer are present in dashboard HTML."""
        r = requests.get(f"{BASE_URL}/dashboard")
        assert r.status_code == 200
        html = r.text
        assert "btn-log-combined" in html
        assert "btn-log-stdout" in html
        assert "btn-log-stderr" in html
        assert "stderr-notice" in html
