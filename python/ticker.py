#!/usr/bin/env python3

from datetime import datetime, timedelta
import finnhub
import json
from pathlib import Path
import re
import threading
import time
import vim


TIME_FORMAT = '%m-%d-%Y %H:%M:%S'
UPDATER = None


def getRESTQuote(rest_api_key, ticker):
    quote = finnhub.Client(api_key=rest_api_key).quote(ticker)
    quote['ticker'] = ticker
    return quote


def getNextUpdateTime(refresh_interval_minutes):
    nextUpdate = datetime.now() + timedelta(minutes=float(refresh_interval_minutes))
    return nextUpdate.strftime(TIME_FORMAT)


def updateCache(params, tickers):
    quoteCacheDir = Path(params['quote_cache_file']).parent
    if not quoteCacheDir.exists():
        quoteCacheDir.mkdir(parents=True)
    quotes = {}
    quotes['next_update'] = getNextUpdateTime(params['refresh_interval_minutes'])
    for t in tickers:
        quotes[t] = getRESTQuote(params['rest_api_key'], t)
    with open(params['quote_cache_file'], 'w') as fp:
        json.dump(quotes, fp, indent=2)
    return quotes


def getCachedQuotes(params, tickers):
    quotes = {}
    quoteCacheFile = Path(params['quote_cache_file'])
    if quoteCacheFile.exists():
        with open(quoteCacheFile, 'r') as fp:
            try:
                quotes = json.load(fp)
            except json.JSONDecodeError as jde:
                print(f'ticker json decode error: {jde.msg} line: {jde.lineno} col: {jde.colno}')
        if quotes:
            for t in tickers:
                quotes[t]['ticker'] = t
            nextUpdate = datetime.strptime(quotes['next_update'], TIME_FORMAT)
            del quotes['next_update']
            # Do the quotes need refreshing? Or did the tracked tickers change, requiring a refresh?
            if nextUpdate > datetime.now() and set(quotes.keys()) == set(tickers):
                return quotes

    quotes = updateCache(params, tickers)
    del quotes['next_update']
    return quotes


# Sample finnhub quote response:
# {
#   'c': 47.08,     # Current price          %c
#   'd': 1.32,      # Change                 %d
#   'dp': 2.8846,   # Percent change         %p
#   'h': 47.116,    # High price of the day  %h
#   'l': 46.02,     # Low price of the day   %l
#   'o': 46.48,     # Open price of the day  %o
#   'pc': 45.76,    # Previous close price   %C
#   't': 1703192401
# }

FMT_PATTERN = (r'(?P<format_specifier>'
               r'(?P<percent>[%])'
               r'(?:(?P<minus>[-]))?'
               r'(?:(?P<width>[\d]+))?'
               r'(?:(?P<dot>[.])(?P<prec>[\d]+))?'
               r'(?P<spec>[cdphloCt%])'
               r')')

class fmtStringParser:
    regex = re.compile(FMT_PATTERN)

    def processSpecifier(self, quote_data, mat):
        """Given a dictionary containing a quote response and an re.Match object
           for a single format specifier, provide the string corresponding to
           the format specifier.

           quote_data : the dict encoded in finnhub quote response format.
           mat : an re.Match object corresponding to a matched regular expression.
        """
        specifier_to_key = {
                             'c': 'c',
                             'd': 'd',
                             'p': 'dp',
                             'h': 'h',
                             'l': 'l',
                             'o': 'o',
                             'C': 'pc',
                             't': 'ticker',
                             '%': '%'
                           }
        gd = mat.groupdict()
        justify = 'r' if gd['minus'] else 'l'
        width = int(gd['width']) if gd['width'] else 0
        prec = int(gd['prec']) if gd['prec'] else 0

        quote_data['%'] = '%' # %% translates to %
        res = str(quote_data[specifier_to_key[gd['spec']]])

        if gd['prec'] and '.' in res:
            d = res.find('.')
            after = prec - len(res[d+1:])
            if after > 0:
                # Not enough precision. Pad with 0's.
                res += '0' * after
            else:
                # Too much precision. Need to truncate.
                res = res[:d+1+prec]

        if gd['width']:
            # A width was specified.
            if len(res) > width:
                # Truncate res to width chars.
                res = res[:width]
            else:
                # Pad res to width chars.
                padding = ' ' * (width - len(res))
                if justify == 'r':
                    res = padding + res
                else:
                    res += padding

        return res

    def parse(self, quote_data, fmt):
        """Given a dictionary containing a quote response and a format
           specifier string, create and return the formatted output string.

           quote_data : the dict encoded in finnhub quote response format.
           fmt : the format string containing arbitrary text and/or format
                 specifiers.
        """
        res = ''
        fmtlen = len(fmt)
        pos = 0
        while pos < fmtlen:
            mat = self.regex.search(fmt, pos)
            if mat:
                start = mat.start()
                if start > pos:
                    # Copy fmt[pos:start] to result.
                    res += fmt[pos:start]
                res += self.processSpecifier(quote_data, mat)
                pos = mat.end()
            else:
                # Copy fmt[pos:] to result.
                res += fmt[pos:]
                pos = fmtlen

        return res


def refreshQuoteDataNow(params, ticker_portfolio):
    updateCache(params, ticker_portfolio.keys())


def getTickerData(params, ticker_portfolio):
    res = {}
    quotes = getCachedQuotes(params, ticker_portfolio.keys())
    parser = fmtStringParser()
    for q in quotes:
        formatted = parser.parse(quotes[q], ticker_portfolio[q])
        res[formatted] = 0 if quotes[q]['dp'] < 0.0 else 1
    return res


class tickerUpdater:
    class tickerThread(threading.Thread):
        def __init__(self, params):
            super().__init__(name='ticker_updater')
            self.running = False
            self.time_to_stop = False
            self.quote_cache_file = params['quote_cache_file']
            self.next_update = self.getNextUpdateTime(self.quote_cache_file)
            self.cond_var = threading.Condition(threading.Lock())

        def getNextUpdateTime(self, quote_cache_file):
            quoteCacheFile = Path(quote_cache_file)
            if not quoteCacheFile.exists():
                return datetime.now()
            quotes = {}
            with open(quoteCacheFile, 'r') as fp:
                try:
                    quotes = json.load(fp)
                except json.JSONDecodeError as jde:
                    print(f'ticker json decode error: {jde.msg} line: {jde.lineno} col: {jde.colno}')
            if quotes:
                return datetime.strptime(quotes['next_update'], TIME_FORMAT)
            return datetime.now()

        def run(self):
            self.running = True

            while True:
                sleep_for = self.next_update - datetime.now()
                with self.cond_var:
                    res = self.cond_var.wait(float(sleep_for.seconds))
                if self.time_to_stop:
                    break
                if not res: # timed out
                    vim.eval('ticker#RefreshQuoteDataNow()')
                    self.next_update = self.getNextUpdateTime(self.quote_cache_file)

            self.running = False

        def is_running(self):
            return self.running

        def stop(self):
            self.time_to_stop = True
            while self.running:
                with self.cond_var:
                    self.cond_var.notify()
                time.sleep(0.01)

    def __init__(self, params):
        self.thread = tickerUpdater.tickerThread(params)
        self.thread.start()

    def stop(self):
        self.thread.stop()
        self.thread.join()

    def is_running(self):
        return self.thread.is_running()


def startDisplayRefresh(params):
    global UPDATER
    if UPDATER is None:
        UPDATER = tickerUpdater(params)
        while not UPDATER.is_running():
            time.sleep(0.01)


def stopDisplayRefresh(params):
    global UPDATER
    if UPDATER is not None:
        UPDATER.stop()
        del UPDATER
        UPDATER = None


if __name__ == '__main__':
    #     'c'         'd'         'p'          'h'          'l'         'o'          'C'
    q = { 'c': 47.08, 'd': 1.32, 'dp': 2.8846, 'h': 47.116, 'l': 46.02, 'o': 46.48, 'pc': 45.76, 't': 1703192401 }

    p = fmtStringParser()
    assert p.parse(q, 'no specifiers') == 'no specifiers'

    assert p.parse(q, '%c') == '47.08'
    assert p.parse(q, '%d') == '1.32'
    assert p.parse(q, '%p') == '2.8846'
    assert p.parse(q, '%h') == '47.116'
    assert p.parse(q, '%l') == '46.02'
    assert p.parse(q, '%o') == '46.48'
    assert p.parse(q, '%C') == '45.76'

    assert p.parse(q, 'before %c') == 'before 47.08'
    assert p.parse(q, '%c after') == '47.08 after'

    assert p.parse(q, '%4p') == '2.88'
    assert p.parse(q, 'before %4p') == 'before 2.88'
    assert p.parse(q, '%4p after') == '2.88 after'

    assert p.parse(q, '%10d') == '1.32      '
    assert p.parse(q, '%-10d') == '      1.32'

    assert p.parse(q, '100%%') == '100%'
    assert p.parse(q, '%4p%%') == '2.88%'

    assert p.parse(q, 'MYSTOCK $%c ($%5h)') == 'MYSTOCK $47.08 ($47.11)'

    assert p.parse(q, '%.2c') == '47.08'
    assert p.parse(q, '%.3c') == '47.080'
    assert p.parse(q, '%.4c') == '47.0800'

    assert p.parse(q, '%.2p') == '2.88'
    assert p.parse(q, '%.3p') == '2.884'
    assert p.parse(q, '%.4p') == '2.8846'
    assert p.parse(q, '%.5p') == '2.88460'

    assert p.parse(q, '%8.5p') == '2.88460 '
    assert p.parse(q, '%-8.5p') == ' 2.88460'

    #params = { 'rest_api_key': 'blah', 'refresh_interval_minutes': 120, 'quote_cache_file': '/home/tswhison/.vim/ticker/ticker_cache.json' }
    #startDisplayRefresh(params)
    #time.sleep(5 * 60.0)
    #stopDisplayRefresh(params)
