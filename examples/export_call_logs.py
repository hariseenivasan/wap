#!/usr/bin/env python3
"""
Example: Export WhatsApp Call Logs with Duration & Dialed Numbers
Extracts recent incoming, outgoing, and missed calls from the Calls tab
via WAP and exports them to a JSON file.

Usage:
    python export_call_logs.py --output calls.json --limit 30
"""
import argparse
import json
import sys
import requests

WAP_URL = "http://localhost:3001"

def export_calls(output_file: str, limit: int = 30, missed_only: bool = False, call_type: str = None):
    print(f"[*] Querying WAP API at {WAP_URL} for call logs...")
    params = {
        "limit": limit,
        "includeDetails": True,
        "missedOnly": missed_only,
    }
    if call_type:
        params["type"] = call_type

    try:
        res = requests.get(f"{WAP_URL}/api/calls", params=params, timeout=45)
        res.raise_for_status()
        calls = res.json()
    except Exception as e:
        print(f"[!] Failed to fetch call logs: {e}")
        sys.exit(1)

    print(f"[+] Retrieved {len(calls)} call records.")
    for c in calls[:5]:
        direction_icon = "📞" if c.get("type") == "audio" else "📹"
        status_flag = "❌ Missed" if c.get("isMissed") else "✅ Answered"
        print(f"  {direction_icon} {c.get('contactName')} ({c.get('phoneNumber') or 'N/A'}) - {status_flag} | Duration: {c.get('duration')} | Time: {c.get('timestamp')}")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(calls, f, indent=2)

    print(f"[+] Call records exported successfully to: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export WhatsApp Call Logs via WAP")
    parser.add_argument("--output", default="calls.json", help="Output file path (default: calls.json)")
    parser.add_argument("--limit", type=int, default=30, help="Maximum number of calls to retrieve (default: 30)")
    parser.add_argument("--missed-only", action="store_true", help="Filter to only missed calls")
    parser.add_argument("--type", choices=["audio", "video"], help="Filter by call type")
    args = parser.parse_args()

    export_calls(args.output, args.limit, args.missed_only, args.type)
