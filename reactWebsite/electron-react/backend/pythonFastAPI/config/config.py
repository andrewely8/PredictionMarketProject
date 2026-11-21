ENVIRONMENTS = {
    "production": {
        "rest": "https://external-api.kalshi.com/trade-api/v2",
        "ws": "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
        "key_field": "Kalshi_production_Api_key",
        "key_file": "kalshiProductionKey.txt"
    },
    "demo": {
        "rest": "https://external-api.demo.kalshi.co/trade-api/v2",
        "ws": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
        "key_field": "Kalshi_demo_Api_key",
        "key_file": "kalshiDemoKey.txt",
    },
}
WS_SIGN_PATH = "/trade-api/ws/v2"