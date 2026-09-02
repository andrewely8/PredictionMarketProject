#This file contains the getting started code from https://docs.kalshi.com/getting_started/api_environments

import json
import requests
import datetime
import base64
from urllib.parse import urlparse
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
import uuid
from urllib.parse import urlparse

#class unauthReq()
# SOURCE: https://docs.kalshi.com/getting_started/quick_start_market_data
# This is the tutorial provided at the above reference, with small modification
# of being able to specify what series you want to look at.
class UnauthReq():
    def __init__(self,series):
        self.series = series

    def makeReq(self):
        # Get series information for SERIES
        url = "https://external-api.kalshi.com/trade-api/v2/series/" + self.series 
        response = requests.get(url)
        series_data = response.json()

        print(f"Series Title: {series_data['series']['title']}")
        print(f"Frequency: {series_data['series']['frequency']}")
        print(f"Category: {series_data['series']['category']}")

        # Get all open markets for SERIES
        markets_url = f"https://external-api.kalshi.com/trade-api/v2/markets?series_ticker="+ self.series +"&status=open"
        markets_response = requests.get(markets_url)
        markets_data = markets_response.json()

        print(f"\nTotal number of markets: ", len(markets_data['markets']))
        print(f"\nActive markets in "+ self.series +" series:")
        for market in markets_data['markets']:
            print(f"- {market['ticker']}: {market['title']}")
            print(f"  Event: {market['event_ticker']}")
            print(f"  Yes Price: ${market['yes_bid_dollars']} | Volume: {market['volume_fp']}")
            print()

        # Get details for a specific event if you have its ticker
        if markets_data['markets']:
            # Let's get details for the first market's event
            event_ticker = markets_data['markets'][0]['event_ticker']
            event_url = f"https://external-api.kalshi.com/trade-api/v2/events/{event_ticker}"
            event_response = requests.get(event_url)
            event_data = event_response.json()

            print(f"Event 0 (first index) Details:")
            print(f"Title: {event_data['event']['title']}")
            print(f"Category: {event_data['event']['category']}")



        # Get orderbook for a specific market
        # Replace with an actual market ticker from the markets list
        if not markets_data['markets']:
            raise ValueError("No open markets found. Try removing status=open or choose another series.")

        market_ticker = markets_data['markets'][0]['ticker']
        orderbook_url = f"https://external-api.kalshi.com/trade-api/v2/markets/{market_ticker}/orderbook"

        orderbook_response = requests.get(orderbook_url)
        orderbook_data = orderbook_response.json()

        print(f"\nOrderbook for {market_ticker}:")
        print("SIZE OF ORDER BOOK: ", len(orderbook_data['orderbook_fp']['yes_dollars']))
        print("YES BIDS:")
        for price_dollars, count_fp in orderbook_data['orderbook_fp']['yes_dollars'][:5]:  # Show top 5
            print(f"  Price: ${price_dollars}, Quantity: {count_fp}")

        print("\nNO BIDS:")
        for price_dollars, count_fp in orderbook_data['orderbook_fp']['no_dollars'][:5]:  # Show top 5
            print(f"  Price: ${price_dollars}, Quantity: {count_fp}")




#class authReq()
# SOURCE: https://docs.kalshi.com/getting_started/quick_start_authenticated_requests
# This is the tutorial provided at the above reference, with small modification
# of being able to specify prediction or demo mode, and API keys pulled from
# external files. 
# 
class AuthReq():

    def __init__(self,mode):
        self.mode = mode # "demo" or "production"
        self.api_key_id_path = './secret/keys.json'

        if self.mode == "demo":
            self.private_key_path = './secret/kalshiDemoKey.txt'
            self.base_url = 'https://external-api.demo.kalshi.co/trade-api/v2'
        elif self.mode == "production":
            self.private_key_path = './secret/kalshiProductionKey.txt'
            self.base_url = 'https://external-api.kalshi.com/trade-api/v2'

        with open(self.api_key_id_path, "rb") as f:
            d = json.load(f)
            if self.mode == "demo":
                self.api_key_id = d["Kalshi_demo_Api_key"]
            elif self.mode == "production":
                self.api_key_id = d["Kalshi_production_Api_key"]

        with open(self.private_key_path, "rb") as f:
            self.private_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())


    def create_signature(self,private_key, timestamp, method, path):
        """Create the request signature."""
        # Strip query parameters before signing
        path_without_query = path.split('?')[0]
        message = f"{timestamp}{method}{path_without_query}".encode('utf-8')
        signature = private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')


    def get(self,private_key, api_key_id, path, base_url):
        """Make an authenticated GET request to the Kalshi API."""
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        # Signing requires the full URL path from root (e.g. /trade-api/v2/portfolio/balance)
        sign_path = urlparse(base_url + path).path
        signature = self.create_signature(private_key, timestamp, "GET", sign_path)

        headers = {
            'KALSHI-ACCESS-KEY': api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp
        }

        return requests.get(base_url + path, headers=headers)


    def get_balance(self):
        response = self.get(self.private_key, self.api_key_id, "/portfolio/balance",self.base_url)
        print(f"Your balance: ${response.json()['balance'] / 100:.2f}")


    #function makeOrder() and post()   -- this is put inside the AuthReq class since it uses authreq().
    # SOURCE: https://docs.kalshi.com/getting_started/quick_start_create_order
    # This is the tutorial provided at the above reference
    #
    def post(self,private_key, api_key_id, path, data, base_url):
        """Make an authenticated POST request to the Kalshi API."""
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        # Signing requires the full URL path from root (e.g. /trade-api/v2/portfolio/events/orders)
        sign_path = urlparse(base_url + path).path
        signature = self.create_signature(private_key, timestamp, "POST", sign_path)

        headers = {
            'KALSHI-ACCESS-KEY': api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json'
        }

        return requests.post(base_url + path, headers=headers, json=data)


    def makeOrder(self):
        # Step 1: Find an open market
        print("Finding an open market...")
        response = requests.get(
            self.base_url + '/markets?limit=100&status=open'
        )

        markets = response.json()['markets']

        try:
            market = next(
                m for m in markets
                if m.get('exchange_index', 0) == 0
            )
        except:
            print("CAN NOT FIND DEMO MARKET")
            return

        print(f"Selected market: {market['ticker']}")
        print(f"Title: {market['title']}")
        print(f"Exchange index: {market['exchange_index']}")
        print(f"Selected: {market['ticker']} - {market['title']}")

        # Step 2: Place a buy order
        print("\nPlacing order...")
        client_order_id = str(uuid.uuid4())
        order_data = {
            "ticker": market['ticker'],
            "side": "bid",
            "count": "1",
            "price": "0.0100",
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": client_order_id
        }

        response = self.post(self.private_key, self.api_key_id, '/portfolio/events/orders', order_data, self.base_url)

        if response.status_code == 201:
            order = response.json()
            print(f"Order placed successfully!")
            print(f"Order ID: {order['order_id']}")
            print(f"Client Order ID: {client_order_id}")
            print(f"Remaining Count: {order['remaining_count']}")
        else:
            print(f"Error: {response.status_code} - {response.text}")


#main
if __name__ == '__main__':

    #call = AuthReq("demo") # OR call = UnauthReq("KXHIGHNY") 
    call = UnauthReq("KXMLBGAME") 
    call.makeReq()
    #call.makeOrder()

