import websockets
import asyncio
import json
import sys
import time
import base64
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding


def load_api_key(api_key_id_path, mode):
	with open(api_key_id_path, "rb") as f:
		d = json.load(f)
		if mode == "demo":
			api_key_id = d["Kalshi_demo_Api_key"]
		elif mode == "production":
			api_key_id = d["Kalshi_production_Api_key"]
	return api_key_id



def load_private_key(mode):
	if mode == "demo":
		private_key_path = 'C:/Users/andre/Desktop/PredictionMarketProject/secret/kalshiDemoKey.txt'
	elif mode == "production":
		private_key_path = 'C:/Users/andre/Desktop/PredictionMarketProject/secret/kalshiProductionKey.txt'

	with open(private_key_path, "rb") as f:
		private_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())

	return private_key



def create_headers(api_key_id, private_key, timestamp, method, path):
		"""Create the request signature."""
		# Strip query parameters before signing
		path_without_query = path.split('?')[0]
		message = f"{timestamp}{method}{path_without_query}".encode('utf-8')
		signature = private_key.sign(
			message,
			padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
			hashes.SHA256()
		)

		generated_signature = base64.b64encode(signature).decode('utf-8')
		auth_headers = {
			"KALSHI-ACCESS-KEY": api_key_id,
			"KALSHI-ACCESS-SIGNATURE": generated_signature,
			"KALSHI-ACCESS-TIMESTAMP": timestamp
		}

		return auth_headers



async def subscribe_to_ticker(websocket):
	"""Subscribe to ticker updates"""
	subscription = {
		"id": 1,
		"cmd": "subscribe",
		"params": {
			"channels": ["ticker"]
		}
	}
	await websocket.send(json.dumps(subscription))



async def subscribe_to_tickers(self):
	"""Subscribe to ticker updates for all markets"""
	subscription_message = {
		"id": self.message_id,
		"cmd": "subscribe",
		"params": {
			"channels": ["ticker"]
		}
	}
	await self.ws.send(json.dumps(subscription_message))
	self.message_id += 1



async def subscribe_to_markets(self, channels, market_tickers):
	"""Subscribe to specific channels and markets"""
	subscription_message = {
		"id": self.message_id,
		"cmd": "subscribe",
		"params": {
			"channels": channels,
			"market_tickers": market_tickers
		}
	}
	await self.ws.send(json.dumps(subscription_message))
	self.message_id += 1



async def subscribe_to_orderbook(websocket, market_tickers):
	"""Subscribe to orderbook updates for specific markets"""
	subscription = {
		"id": 2,
		"cmd": "subscribe",
		"params": {
			"channels": ["orderbook_delta"],
			"market_tickers": market_tickers
		}
	}
	await websocket.send(json.dumps(subscription))



async def process_message(message):
	"""Process incoming WebSocket messages"""
	data = json.loads(message)
	msg_type = data.get("type")

	if msg_type == "ticker":
		# Handle ticker update
		market = data["msg"]["market_ticker"]
		bid = data["msg"]["yes_bid_dollars"]
		ask = data["msg"]["yes_ask_dollars"]
		print(f"{market}: Yes Bid ${bid}, Yes Ask ${ask}")

	elif msg_type == "orderbook_snapshot":
		# Handle full orderbook state
		print(f"Orderbook snapshot for {data['msg']['market_ticker']}")

	elif msg_type == "orderbook_delta":
		# Handle orderbook changes
		print(f"Orderbook update for {data['msg']['market_ticker']}")
		# Note: client_order_id field is optional - present only when you caused this change
		if 'client_order_id' in data['msg']:
			print(f"  Your order {data['msg']['client_order_id']} caused this change")

	elif msg_type == "error":
		error_code = data.get("msg", {}).get("code")
		error_msg = data.get("msg", {}).get("msg")
		print(f"Error {error_code}: {error_msg}")



# Connect with authentication
async def connect(ws_url, auth_headers,market_tickers, save_dir):
	async with websockets.connect(uri=ws_url, additional_headers=auth_headers) as websocket:
		print("Connected to Kalshi WebSocket", flush=True)

		# Subscribe to orderbook
		# if We passed multiple market tickers in the market_tickers list, use "market_tickers": market_tickers
		# if We passed ONE market ticker in the market_tickers list, use fist one, "market_ticker": market_tickers[0]
		if len(market_tickers) >= 2:
			subscribe_msg = {
				"id": 1,
				"cmd": "subscribe",
				"params": {
					"channels": ["orderbook_delta"],
					"market_tickers": market_tickers
				}
			}
			await websocket.send(json.dumps(subscribe_msg))
		else:
			subscribe_msg = {
				"id": 1,
				"cmd": "subscribe",
				"params": {
					"channels": ["orderbook_delta"],
					"market_ticker": market_tickers[0]  
				}
			}
			await websocket.send(json.dumps(subscribe_msg))

		# Process messages
		with open(f"{save_dir}/{market_tickers[0]}.jsonl", "a", encoding="utf-8") as f:
			async for message in websocket:
				f.write(message + "\n")



async def handle_message(message,ws_url,api_key_id,private_key):
	#TODO:
	#Check time is in future/correct format
	#Check time is specified if scheduling is on
	#Check market tickers are in same market
	print(message, flush=True)
	market_tickers = message['market_tickers']
	save_dir = message['save_dir']
	scheduled_ahead = message['scheduled_ahead']
	time_input = message['time_input']
	time_ampm = message['time_ampm']
	splitMarketTickers = market_tickers.split(",")
	stripSplitMarketTickers = []
	for s in splitMarketTickers:
		stripSplitMarketTickers.append(s.strip())

	timestamp = str(int(time.time() * 1000))
	generated_auth_headers = create_headers(api_key_id, private_key, timestamp, "GET", "/trade-api/ws/v2")

	#Run the connection
	await connect(ws_url, generated_auth_headers, stripSplitMarketTickers, save_dir)



async def main():
	MODE = "production"
	API_KEY_ID_PATH = "C:/Users/andre/Desktop/PredictionMarketProject/secret/keys.json"
	if MODE == "production":
		ws_url = "wss://external-api-ws.kalshi.com/trade-api/ws/v2" 
	elif MODE == "demo":
		ws_url = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
	api_key_id = load_api_key(API_KEY_ID_PATH, MODE)
	private_key = load_private_key(MODE)

	while True:
		line = await asyncio.to_thread(sys.stdin.readline)

		if not line:
			break

		message = json.loads(line)
		asyncio.create_task(handle_message(message,ws_url,api_key_id,private_key))



if __name__ == "__main__":
	asyncio.run(main())

			


