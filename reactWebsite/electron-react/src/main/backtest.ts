
type orderbookSnapshotMessage = {
	market_ticker: string;
	market_id: string;
	yes_dollars_fp: [string,string][];
	no_dollars_fp: [string,string][];
}

type orderbookSubscribedMessage = {
	channel: string;
	sid: number;
}

type orderbookDeltaMessage = {
	market_ticker: string;
	market_id: string;
	price_dollars: string;
	delta_fp: string;
	side: string;
	ts: string;
	ts_ms: number;
}


type orderbookSnapshot = {
	type: "orderbook_snapshot";
	sid: number;
	seq: number;
	msg: orderbookSnapshotMessage;
}

type orderbookSubscribed = {
	type: "subscribed";
	id: number;
	msg: orderbookSubscribedMessage;
}

type orderbookDelta = {
	type: "orderbook_delta";
	sid: number;
	seq: number;
	msg: orderbookDeltaMessage;
}


type orderbookEvent = | orderbookSnapshot | orderbookSubscribed | orderbookDelta;

type orderbook = {
	yes_dollars_fp: [string,string][];
	no_dollars_fp: [string,string][];
}

export type topBook = {
	best_yes_bid_dollars: string;
	best_yes_bid_volume: string; 
	best_yes_ask_dollars: string; 
	best_yes_ask_volume: string;
	best_no_bid_dollars: string; 
	best_no_bid_volume: string;
	best_no_ask_dollars: string; 
	best_no_ask_volume: string; 
}



function decimalToBigInt(value: string, decimals: number): bigint {
	const [whole, frac = ""] = value.split(".");
	const paddedFrac = frac.padEnd(decimals,"0").slice(0,decimals);

	return BigInt(whole+paddedFrac);
};

function bigIntToDecimal(value: bigint, decimals: number): string {
	const str = value.toString().padStart(decimals+1,"0");
	const whole = str.slice(0,-decimals);
	const frac = str.slice(-decimals);

	return `${whole}.${frac}`;
}



export class Backtester {
  dataArray: orderbookEvent[];
  numMarkets: number;
  currentIndex: number;
  orderbooks: Map<string, orderbook>;
  tickers: string[];
  timeOffset: number;
  currentTime: number;

  constructor(dataArray: orderbookEvent[], numMarkets?: number) {
    this.dataArray = dataArray;
    this.orderbooks = new Map();
    this.tickers = [];
    this.currentTime = 0;

    if (this.dataArray[0].type !== "subscribed") {
    	throw new Error("expected first data entry to be of subscribed type");
    } else {
    	this.currentIndex = 1;
    }    

    if (numMarkets) {
    	this.numMarkets = numMarkets;

    	for (this.currentIndex; this.currentIndex < this.numMarkets+1; this.currentIndex++) {
    		if (this.dataArray[this.currentIndex].type !== "orderbook_snapshot") {
    			throw new Error(`expected ${this.currentIndex}th data entry to be of orderbook_snapshot type since numMarkets=${this.numMarkets} was specified.`);
    		} else {
    			const currentSnapMsg = this.dataArray[this.currentIndex].msg;
    			this.tickers.push(currentSnapMsg.market_ticker);
    			this.orderbooks.set(currentSnapMsg.market_ticker, {
    				yes_dollars_fp: currentSnapMsg.yes_dollars_fp,
    				no_dollars_fp: currentSnapMsg.no_dollars_fp,
    			})
    		}
    	}

    } else { 
    	while (this.dataArray[this.currentIndex].type === "orderbook_snapshot") {
    		const currentSnapMsg = this.dataArray[this.currentIndex].msg;
    		this.tickers.push(currentSnapMsg.market_ticker);
  			this.orderbooks.set(currentSnapMsg.market_ticker, {
  				yes_dollars_fp: currentSnapMsg.yes_dollars_fp,
  				no_dollars_fp: currentSnapMsg.no_dollars_fp,
  			})
  			this.currentIndex += 1;
    	}
    }

    this.timeOffset = this.dataArray[this.currentIndex].msg.ts_ms

  }

  getTopOrderbook(ticker: string): topBook {
  	const currentBook = this.orderbooks.get(ticker);
  	const currentBookYD = currentBook.yes_dollars_fp;
  	const currentBookND = currentBook.no_dollars_fp;

		const byb_d = decimalToBigInt(currentBook.yes_dollars_fp[currentBookYD.length-1][0],4)
		const byb_q = decimalToBigInt(currentBook.yes_dollars_fp[currentBookYD.length-1][1],2)
		const bnb_d = decimalToBigInt(currentBook.no_dollars_fp[currentBookND.length-1][0],4)
		const bnb_q = decimalToBigInt(currentBook.no_dollars_fp[currentBookND.length-1][1],2)
		const bya_d = decimalToBigInt("1.0000",4) - bnb_d
		const bya_q = bnb_q
		const bna_d = decimalToBigInt("1.0000",4) - byb_d
		const bna_q = byb_q
  	
  	const topOfBook: topBook = {
			best_yes_bid_dollars: bigIntToDecimal(byb_d,4),
			best_yes_bid_volume: bigIntToDecimal(byb_q,2),
			best_yes_ask_dollars: bigIntToDecimal(bya_d,4),
			best_yes_ask_volume: bigIntToDecimal(bya_q,2),
			best_no_bid_dollars: bigIntToDecimal(bnb_d,4),
			best_no_bid_volume: bigIntToDecimal(bnb_q,2),
			best_no_ask_dollars: bigIntToDecimal(bna_d,4), 
			best_no_ask_volume: bigIntToDecimal(bna_q,2),
  	};

  	return topOfBook;
  }


  getTopOrderbooks(): Map<string,topBook> {
  	const topOfBooks = new Map();

  	for (let i=0; i < this.tickers.length; i++) {
  		const currTopOfBook = this.getTopOrderbook(this.tickers[i]);
  		topOfBooks.set(this.tickers[i], currTopOfBook);
  	}

  	return topOfBooks;
  }


  setCurrentTime(currentTime: number) {
  	this.currentTime = currentTime;
  }


  updateOrderbook(newEvent: orderbookEvent) {
  	const msg = newEvent.msg;
  	const tkr = msg.market_ticker;
  	const side = msg.side;
		const price_changed_str = msg.price_dollars;
		const price_changed_dec = decimalToBigInt(price_changed_str,4);
		const volume_changed_str = msg.delta_fp;
		const volume_changed_dec = decimalToBigInt(volume_changed_str,2);
		const currentOrderbook = this.orderbooks.get(tkr);
		const newList = [];

		let found = false;
		let currentOrderbookSide;

		if (side === "yes") {
			currentOrderbookSide = currentOrderbook.yes_dollars_fp;
		} else if (side === "no") {
			currentOrderbookSide = currentOrderbook.no_dollars_fp;
		}


		for (let i=0; i < currentOrderbookSide.length; i++ ) {
			const existing_price_str = currentOrderbookSide[i][0]
			const existing_volume_str = currentOrderbookSide[i][1]
			const existing_price_dec = decimalToBigInt(existing_price_str,4);
			const existing_volume_dec = decimalToBigInt(existing_volume_str,2);

			if (price_changed_dec === existing_price_dec) {
				if (found) {
					throw new Error("found same price twice in orderbook");
				}
				found = true;
				const new_volume_dec = existing_volume_dec + volume_changed_dec;

				if (new_volume_dec > 0) {
					const new_volume_str = bigIntToDecimal(new_volume_dec,2);
					newList.push([existing_price_str,new_volume_str]);
				} else if (new_volume_dec < 0) {
					throw new Error("orderbook has negative volume");
				}

			} else if (!found && price_changed_dec < existing_price_dec) {
				found = true;
				newList.push([price_changed_str,volume_changed_str]);
				newList.push([existing_price_str,existing_volume_str]);
			} else {
				newList.push([existing_price_str,existing_volume_str]);
			}

		}

		if (!found) {
			newList.push([price_changed_str,volume_changed_str]);
		}

		if (side === "yes") {
			const itemRef = this.orderbooks.get(tkr);
			itemRef.yes_dollars_fp = newList;
		} else if (side === "no") {
			const itemRef = this.orderbooks.get(tkr);
			itemRef.no_dollars_fp = newList;
		}

		

  }


  processTick(currentTime: number) {
		this.setCurrentTime(currentTime);
		while (this.currentIndex < this.dataArray.length &&
			this.currentTime >= this.dataArray[this.currentIndex].msg.ts_ms - this.timeOffset
		) {
			this.updateOrderbook(this.dataArray[this.currentIndex]);
			this.currentIndex += 1;
		}

	}


}