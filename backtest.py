import json
import time
from decimal import *

def parseDataFile(filepath):
	lineCount = 0
	fileArr = []
	with open(filepath, 'r') as file:
		for line in file:
			if line != "\n":
				jsonLine = json.loads(line)
				fileArr.append(jsonLine)
				lineCount += 1
	
	print("read", lineCount, "lines from", filepath,"\n")

	return fileArr



class MlbGame():
	def __init__(self,filepath,numberMarkets=None):
		self.marketsTracked = []
		self.data = parseDataFile(filepath)
		self.initialMarketOrderbooks = []
		self.currentOrderbooks = {}
		self.numUpdates = 0

		if self.data[0]["type"] != "subscribed":
			raise Exception(f"[Program defined Error] expected first line of {filepath} to be a subscribed type")

		i = 1
		while self.data[i]["type"] == "orderbook_snapshot":
			self.marketsTracked.append(self.data[i]['msg']['market_ticker'])
			self.initialMarketOrderbooks.append(self.data[i])
			i += 1
		if numberMarkets and len(self.marketsTracked) != numberMarkets:
			raise Exception(f"[Program defined Error] expected {numberMarkets} markets but found {len(self.marketsTracked)}")
		elif not numberMarkets:
			print(f"number of markets not specified, found {len(self.marketsTracked)} markets tracked\n")
		
		self.AbsoluteTrackStartTime = self.data[i]['msg']['ts_ms']
		self.AbsoluteTrackEndTime = self.data[-1]['msg']['ts_ms'] - self.AbsoluteTrackStartTime
		self.currentTime = 0
		self.currentDataIdx = i
		
		for initialBook in self.initialMarketOrderbooks:
			msg = initialBook["msg"]
			tkr = msg["market_ticker"]
			yes_dollars_fp = msg["yes_dollars_fp"]
			no_dollars_fp = msg["no_dollars_fp"]

			currentBook = {"yes_dollars_fp": yes_dollars_fp, "no_dollars_fp": no_dollars_fp}
			self.currentOrderbooks[tkr] = currentBook


	def getTopOfBook(self,ticker):
		currentBook = self.currentOrderbooks[ticker]

		byb_d = Decimal(currentBook["yes_dollars_fp"][-1][0]) #best yes bid dollars
		byb_q = Decimal(currentBook["yes_dollars_fp"][-1][1]) #best yes bid volume
		bnb_d = Decimal(currentBook["no_dollars_fp"][-1][0])  #best no bid dollars
		bnb_q = Decimal(currentBook["no_dollars_fp"][-1][1])  #best no bid volume
		bya_d = Decimal(1.00) - bnb_d	    		  #best yes ask dollars
		bya_q = bnb_q	    						  #best yes ask volume
		bna_d = Decimal(1.00) - byb_d				  #best no ask dollars
		bna_q = byb_q  								  #best no ask volume

		topOfBook = {
			"best_yes_bid_dollars": byb_d, "best_yes_bid_volume": byb_q, 
			"best_yes_ask_dollars": bya_d, "best_yes_ask_volume": bya_q,
			"best_no_bid_dollars":  bnb_d, "best_no_bid_volume":  bnb_q,
			"best_no_ask_dollars":  bna_d, "best_no_ask_volume":  bna_q, 
		}
		return topOfBook


	def getMarkets(self):
		return self.marketsTracked


	def stepTime(self,timeStepMs=1):
		self.currentTime += timeStepMs


	def updateOrderbook(self,newDataLine):

		msg = newDataLine["msg"]
		tkr = msg["market_ticker"]
		side = msg["side"]
		price_changed_str = msg["price_dollars"]
		price_changed_dec = Decimal(msg["price_dollars"])
		volume_change_str = msg["delta_fp"]
		volume_change_dec = Decimal(msg["delta_fp"])
		currentOrderBook = self.currentOrderbooks[tkr]

		newList = []
		found = False
		if side == "yes":
			bookSideKey = "yes_dollars_fp"
		elif side == "no":
			bookSideKey = "no_dollars_fp"
		
		for price, volume in currentOrderBook[bookSideKey]:
			existing_price_dec = Decimal(price)

			if price_changed_dec == existing_price_dec:
				if found:
					raise Exception("[PROGRAM DEFINED ERROR] found same price twice in orderbook")
				found = True
				new_volume = Decimal(volume) + volume_change_dec

				if new_volume > 0:
					newList.append([price,str(new_volume)])
				elif new_volume < 0:
					raise Exception("[PROGRAM DEFINED ERROR] orderbook has negative volume")

			elif not found and price_changed_dec < Decimal(price):
				found = True
				newList.append([price_changed_str,volume_change_str])
				newList.append([price, volume])
			else:
				newList.append([price, volume])

		if not found:
			newList.append([price_changed_str,volume_change_str])
		self.currentOrderbooks[tkr][bookSideKey] = newList
		
		self.numUpdates += 1


	def checkEvent(self,time):
		while time >= (self.data[self.currentDataIdx]["msg"]["ts_ms"]-self.AbsoluteTrackStartTime):
			self.updateOrderbook(self.data[self.currentDataIdx])
			self.currentDataIdx += 1


	def getOrderBooks(self):
		return self.currentOrderbooks





if __name__ == "__main__":
	
	FILE_PATH_1 = "./collectedData/MLB/KXMLBGAME-26SEP051915NYYSD.jsonl"

	game1 = MlbGame(FILE_PATH_1)


	# Test of MlbGame.updateOrderbook()
	print("\n\n")
	print(game1.currentOrderbooks['KXMLBGAME-26SEP051915NYYSD-NYY'])
	
	testCases = [
		{"type":"orderbook_delta","sid":1,"seq":1,"msg":{"market_ticker":"KXMLBGAME-26SEP051915NYYSD-NYY","market_id":"11014e93-6b1c-4b0d-8f07-737a9108ee1b","price_dollars":"0.4500","delta_fp":"-1437.00","side":"yes","ts":"2026-09-05T23:00:00.096819Z","ts_ms":1788649200096}},
		{"type":"orderbook_delta","sid":1,"seq":2,"msg":{"market_ticker":"KXMLBGAME-26SEP051915NYYSD-NYY","market_id":"11014e93-6b1c-4b0d-8f07-737a9108ee1b","price_dollars":"0.2800","delta_fp":"143.00","side":"yes","ts":"2026-09-05T23:00:00.096819Z","ts_ms":1788649200099}},
		{"type":"orderbook_delta","sid":1,"seq":3,"msg":{"market_ticker":"KXMLBGAME-26SEP051915NYYSD-NYY","market_id":"11014e93-6b1c-4b0d-8f07-737a9108ee1b","price_dollars":"0.4600","delta_fp":"437.00","side":"yes","ts":"2026-09-05T23:00:00.096819Z","ts_ms":1788649200110}},
		{"type":"orderbook_delta","sid":1,"seq":4,"msg":{"market_ticker":"KXMLBGAME-26SEP051915NYYSD-NYY","market_id":"11014e93-6b1c-4b0d-8f07-737a9108ee1b","price_dollars":"0.2700","delta_fp":"137.00","side":"no","ts":"2026-09-05T23:00:00.096819Z","ts_ms":1788649200115}},
		{"type":"orderbook_delta","sid":1,"seq":4,"msg":{"market_ticker":"KXMLBGAME-26SEP051915NYYSD-NYY","market_id":"11014e93-6b1c-4b0d-8f07-737a9108ee1b","price_dollars":"0.2300","delta_fp":"-6629.00","side":"no","ts":"2026-09-05T23:00:00.096819Z","ts_ms":1788649200125}},
	]

	for test in testCases:
		print("\n")
		game1.updateOrderbook(test)
		print(game1.currentOrderbooks['KXMLBGAME-26SEP051915NYYSD-NYY'])
	
	