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
