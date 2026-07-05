from fastapi import Request
from backend.core.security import client_ip

def test_client_ip_extraction():
    # Helper to mock request
    def make_request(host, headers):
        scope = {
            "type": "http",
            "client": (host, 12345),
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()]
        }
        return Request(scope)

    # 1. Normal client without proxy
    req = make_request("192.168.1.10", {})
    assert client_ip(req) == "192.168.1.10"

    # 2. CF-Connecting-IP takes precedence when from localhost
    req = make_request("127.0.0.1", {"cf-connecting-ip": "203.0.113.1", "x-forwarded-for": "198.51.100.1"})
    assert client_ip(req) == "203.0.113.1"

    # 3. X-Forwarded-For is used if CF-Connecting-IP is missing
    req = make_request("127.0.0.1", {"x-forwarded-for": "198.51.100.1, 10.0.0.1"})
    assert client_ip(req) == "198.51.100.1"

    # 4. Fallback to host if no headers
    req = make_request("127.0.0.1", {})
    assert client_ip(req) == "127.0.0.1"

    # 5. Untrusted proxy (not 127.0.0.1/::1) cannot spoof headers
    req = make_request("192.168.1.10", {"cf-connecting-ip": "203.0.113.1"})
    assert client_ip(req) == "192.168.1.10"
