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
import time
from collections import defaultdict

class UnauthReq():
    def __init__(self):
        pass

    def getOrderBook(self,market_ticker,order_book_depth,print_statements=False):
        orderbook_url = f"https://external-api.kalshi.com/trade-api/v2/markets/{market_ticker}/orderbook"
        orderbook_response = requests.get(orderbook_url)
        orderbook_data = orderbook_response.json()
        orderbook_data_clean = defaultdict(list)

        if print_statements:
            print(f"\nOrderbook for {market_ticker}:")
            print("SIZE OF ORDER BOOK: ", len(orderbook_data['orderbook_fp']['yes_dollars']))
            print("YES BIDS:")

        for price_dollars, count_fp in orderbook_data['orderbook_fp']['yes_dollars'][-order_book_depth:]:
            orderbook_data_clean["yes"].append({'price': price_dollars, 'quantity': count_fp})
            if print_statements:
                print(f"  Price: ${price_dollars}, Quantity: {count_fp}")

        if print_statements:
            print("\nNO BIDS:")
        for price_dollars, count_fp in orderbook_data['orderbook_fp']['no_dollars'][-order_book_depth:]:
            orderbook_data_clean["no"].append({'price': price_dollars, 'quantity': count_fp})
            if print_statements:
                print(f"  Price: ${price_dollars}, Quantity: {count_fp}")

        return orderbook_data_clean


    def findArb(self,market_ticker,num_tries):
        flg = 0
        for i in range(num_tries):
            
            orderbook_url = f"https://external-api.kalshi.com/trade-api/v2/markets/{market_ticker}/orderbook"
            orderbook_response = requests.get(orderbook_url)
            orderbook_data = orderbook_response.json()
            highestYesBid_price, highestYesBid_quantity  = orderbook_data['orderbook_fp']['yes_dollars'][-1]       
            highestNoBid_price, highestNoBid_quantity = orderbook_data['orderbook_fp']['no_dollars'][-1]

            print("Fetch number: ", i)
            print(f'\thighestYesBid_price: {highestYesBid_price}')
            print(f'\thighestNoBid_price: {highestNoBid_price}')

            if float(highestYesBid_price) + float(highestNoBid_price) > 1:
                flg += 1
                print(f"  ARB FOUND: ")
                print(f"  YES BID: Price: ${highestYesBid_price}, Quantity: {highestYesBid_quantity}")
                print(f"  No  BID: Price: ${highestNoBid_price}, Quantity: {highestNoBid_quantity}")
            
        if flg:
            print("*******#######   FOUND ARB(S)   #######*******")
        else:
            print("-no arb found-")           


    def findCombArb(self,market_ticker_ML,market_ticker_SP,num_tries):
        
        flg = 0
        for i in range(num_tries):
            #print("Fetch number: ", i)
            ml_data = self.getOrderBook(market_ticker_ML,1)
            sp_data = self.getOrderBook(market_ticker_SP,1)

            ask_sp = 1 - float(sp_data['yes'][0]['price'])
            ask_ml = 1 - float(ml_data['no'][0]['price'])

            if ask_sp + ask_ml < 1.00:
                flg = 1
                print(f"  ARB FOUND: ")
                print(ml_data)
                print(sp_data)

        if flg:
            return True
        else:
            return False 
        


#main
if __name__ == '__main__':

    TICKER = "KXATPGSPREAD-26SEP01CERGEA"
    
    MONEY_LINE_TICKER_1 = "KXATPMATCH-26SEP01CERGEA-GEA"
    SPREAD_TICKER_1 = "KXATPGSPREAD-26SEP01CERGEA-GEA2"

    MONEY_LINE_TICKER_2 = "KXATPMATCH-26SEP01CERGEA-CER"
    SPREAD_TICKER_2 = "KXATPGSPREAD-26SEP01CERGEA-CER2"
    
    call = UnauthReq()
    #call.findArb(TICKER,10)
    i = 0 
    trials = 100
    while i <= trials:
        print("TRIAL NUMBER ", i, "\n")
        i += 1
        #call.findCombArb(MONEY_LINE_TICKER_1,SPREAD_TICKER_1,1)
        call.findCombArb(MONEY_LINE_TICKER_2,"KXATPEXACTMATCH-26SEP01CERGEA-GEA32",1)
        time.sleep(3)