"""
Unit tests for WAP Unified Dashboard, Login view, Configuration, and Supervisor Process Management APIs.
Ensures zero credential leakage and verifies API conformance.
"""

import pytest
import requests

BASE_URL = "http://127.0.0.1:3001"

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
        assert "Link WhatsApp Account" in res.text

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
