#!/usr/bin/env python3
# MIT License
#
# Copyright (c) 2023 Tim Whisonant
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Python backend for the Ticker Vim plugin.

Uses the Finnhub API client module to retrieve stock data for a
pre-defined set of stock ticker symbols.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import threading
import time
import finnhub
import vim


TIME_FORMAT = '%m-%d-%Y %H:%M:%S'
ENCODING = 'utf-8'
UPDATER = None


def get_rest_quote(rest_api_key: str, ticker: str) -> dict:
    """Use the REST API to retrieve a stock quote.

    Given a Finnhub API key and a ticker symbol, retrieve
    current quote data for that ticker symbol, returning
    the quote dictionary.

    Args:
      rest_api_key:
        Finnhub REST API key
      ticker:
        Stock ticker symbol

    Returns:
      A dict populated with the Finnhub quote keys, with
      one additional key for the 'ticker' itself.
      https://finnhub.io/docs/api/quote
    """
    quote = finnhub.Client(api_key=rest_api_key).quote(ticker)
    quote['ticker'] = ticker
    return quote


def calc_next_update(refresh_interval_minutes: int) -> str:
    """Given the refresh interval, find the next refresh time.

    Given the value of g:ticker_refresh_interval_minutes, use
    the current time to find the next update time. Convert this
    next update time to a string.

    Args:
      refresh_interval_minutes:
        The value of g:ticker_refresh_interval_minutes

    Returns:
      A string representing the next update time, formatted
      using TIME_FORMAT.
    """
    next_update = datetime.now() + timedelta(minutes=float(refresh_interval_minutes))
    return next_update.strftime(TIME_FORMAT)


def update_cache(params: dict, tickers: list) -> dict:
    """Use the REST API to fetch quotes, updating the cache file.

    Given g:ticker_parameters and the list of ticker symbols,
    use the REST API to fetch a quote for each symbol, assembling
    each quote into a dictionary.

    Args:
      params:
        The value of g:ticker_parameters.
      tickers:
        A list of stock ticker symbol strings.

    Returns:
      A dict of all the stock quotes, indexed by the ticker
      symbol.
    """
    quote_cache_dir = Path(params['quote_cache_file']).parent
    if not quote_cache_dir.exists():
        quote_cache_dir.mkdir(parents=True)
    quotes = {}
    quotes['next_update'] = calc_next_update(params['refresh_interval_minutes'])
    for t in tickers:
        quotes[t] = get_rest_quote(params['rest_api_key'], t)
    with open(params['quote_cache_file'], 'w', encoding=ENCODING) as fp:
        json.dump(quotes, fp, indent=2)
    return quotes


def refresh_quote_data_now(params: dict, ticker_portfolio: dict):
    """Refresh all quote data, writing a new quote cache file.

    Immediately fetch new quote data for the entire portfolio,
    writing a new quote cache file.

    Args:
      params:
        The value of g:ticker_parameters.
      ticker_portfolio:
        The value of g:ticker_portfolio.
    """
    update_cache(params, ticker_portfolio.keys())


def get_cached_quotes(params: dict, tickers: list) -> dict:
    """Read the stock quotes from cache, or retrieve new data.

    If the quote cache file exists, read the cached data from the file.
    If the JSON decode is successful and the set of tickers appearing
    in the quote data matches that stored in the ticker parameter,
    Then examine the next update time from the file. If the current time
    is less than the next update time, then return the cached quote
    data, else use tickers to request new quote data, updating the
    cache.

    Args:
      params:
        The value of g:ticker_parameters.
      tickers:
        A list of stock ticker symbol strings.

    Returns:
      A dict of all the stock quotes, indexed by the ticker
      symbol.
    """
    quotes = {}
    quote_cache_file = Path(params['quote_cache_file'])
    if quote_cache_file.exists():
        with open(quote_cache_file, 'r', encoding=ENCODING) as fp:
            try:
                quotes = json.load(fp)
            except json.JSONDecodeError as jde:
                print(f'ticker json decode error: {jde.msg} '
                      f'line: {jde.lineno} col: {jde.colno}')
            else:
                next_update = datetime.strptime(quotes['next_update'],
                                                TIME_FORMAT)
                del quotes['next_update']

        if quotes and set(quotes.keys()) == set(tickers):
            for t in tickers:
                quotes[t]['ticker'] = t
            # Do the quotes need refreshing?
            if next_update > datetime.now():
                return quotes

    # Refresh all the quote data, updating the quote cache file.
    quotes = update_cache(params, tickers)
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

class FmtStringParser:
    """Performs format string search and replace.

    In the style of printf formatting for floating-point numbers,
    convert a format string consisting of arbitrary text and
    format specifiers to its translated form.

    The set of input format specifiers is defined in the
    specifer_to_key variable below. When a specifier string is
    encountered in the format string, the specifier is used as
    an index to find the correct dict key for the quote response
    data.

    The form of the format specifier is %-8.2a, where the optional
    '-' indicates right justification, '8' indicates a total field
    width of 8 columns, the optional '.2' indicates the number of
    digits after the decimal point, and 'a' indicates the format
    specifier.
    """

    regex = re.compile(FMT_PATTERN)

    def process_specifier(self, quote_data: dict, mat: re.Match) -> str:
        """Given a matched format specifier, compute its final form.

        Given a dictionary containing a quote response and an re.Match object
        for a single format specifier, provide the string corresponding to
        the format specifier.

        Args:
         quote_data:
           The dict encoded in Finnhub quote response format.
         mat:
           An re.Match object corresponding to a matched regular
           expression from the format specifier string.

        Returns:
          A string formatted per the input specifier.
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

    def parse(self, quote_data: dict, fmt: str) -> str:
        """Convert a format specifier string to its final form.

        Given a dictionary containing quote responses and a format
        specifier string, create and return the formatted output string.

        Args:
          quote_data:
            The dict encoded in Finnhub quote response format.
          fmt:
            The format string containing arbitrary text and/or
            format specifiers.

        Returns:
          The the resulting string from converting each of the
          format specifiers.
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
                res += self.process_specifier(quote_data, mat)
                pos = mat.end()
            else:
                # Copy fmt[pos:] to result.
                res += fmt[pos:]
                pos = fmtlen

        return res


def get_ticker_data(params: dict, ticker_portfolio: dict) -> dict:
    """Retrieve quote data from cache, updating the cache as needed.

    Attempt to retrieve the quote data for ticker_portfolio from
    cache. If the set of keys in ticker_portfolio doesn't match
    the set of keys stored in the quote cache file, then fetch and
    return new data. If the 'next_update' timestamp from the quote
    cache has expired, then fetch and return new data.

    Args:
      params:
        The value of g:ticker_parameters.
      ticker_portfolio:
        The value of g:ticker_portfolio.

    Returns:
      A dict mapping the formatted display data to a 0 or 1. If the
      formatted display data maps to 0, then the display area will
      be highlighted with g:ticker_down_highlight. Otherwise, the
      display area will be highlighted with g:ticker_up_highlight.
    """
    res = {}
    quotes = get_cached_quotes(params, ticker_portfolio.keys())
    parser = FmtStringParser()
    for quote in quotes:
        formatted = parser.parse(quotes[quote], ticker_portfolio[quote])
        res[formatted] = 0 if quotes[quote]['dp'] < 0.0 else 1
    return res


class TickerUpdater:
    """Refresh Ticker display when refresh interval expires.

    Waits for the 'next_update' timeout from the quote cache,
    then updates the quote cache file and forces a display refresh.
    """

    class TickerThread(threading.Thread):
        """Specialization of threading.Thread that updates the cache.

        The thread waits on a condition variable that is set to expire
        on 'next_update'. When the thread wakes, it checks to see the
        cause of the wake, which may be a signal to quit or a timeout
        of 'next_update'.
        """

        def __init__(self, params: dict):
            """Initialize the threading object.

            The thread tracks the location of the quote cache file
            and a condition variable that is set to expire on
            'next_update'.

            Args:
              params:
                The value of g:ticker_parameters.
            """
            super().__init__(name='ticker_updater')
            self.running = False
            self.time_to_stop = False
            self.quote_cache_file = params['quote_cache_file']
            self.next_update = self.get_next_update_time(self.quote_cache_file)
            self.cond_var = threading.Condition(threading.Lock())

        def get_next_update_time(self, quote_cache_file: str) -> datetime:
            """Determine the 'next_update' time.

            If the quote cache file doesn't exist or if it has been
            corrupted somehow such that it doesn't parse, then return
            the current datetime. Otherwise, parse the 'next_update'
            key from the quote cache, returning the corresponding
            datetime.

            Args:
              quote_cache_file:
                The value of g:ticker_quote_cache_file

            Returns:
              The datetime object corresponding to the 'next_update'
              key found in the file, or the current datetime object.
            """
            quote_cache = Path(quote_cache_file)
            if not quote_cache.exists():
                return datetime.now()
            quotes = {}
            with open(quote_cache, 'r', encoding=ENCODING) as fp:
                try:
                    quotes = json.load(fp)
                except json.JSONDecodeError as jde:
                    print(f'ticker json decode error: {jde.msg} '
                          f'line: {jde.lineno} col: {jde.colno}')
            if quotes:
                return datetime.strptime(quotes['next_update'], TIME_FORMAT)
            return datetime.now()

        def run(self):
            """Sleep until 'next_update' or time to stop.

            If we wake, and self.time_to_stop has been set, then
            stop immediately. Otherwise, check the result from
            waiting on our condition. If the variable was not signaled,
            then we timed out and need to update the quote cache and
            force a refresh of the popups.
            """
            self.running = True

            while True:
                if self.time_to_stop:
                    break
                now = datetime.now()
                if now >= self.next_update:
                    vim.eval('ticker#RefreshQuoteDataNow()')
                    self.next_update = \
                        self.get_next_update_time(self.quote_cache_file)
                else:
                    sleep_for = self.next_update - now
                    with self.cond_var:
                        self.cond_var.wait(float(sleep_for.seconds))

            self.running = False

        def is_running(self):
            """Is the thread still running?
            """
            return self.running

        def stop(self):
            """Tell the thread to stop, and wait for it to stop.
            """
            self.time_to_stop = True
            while self.running:
                with self.cond_var:
                    self.cond_var.notify()
                time.sleep(0.01)

    def __init__(self, params: dict):
        """Create and start the updater thread.

        Args:
          params:
            The value of g:ticker_parameters.
        """
        self.thread = TickerUpdater.TickerThread(params)
        self.thread.start()

    def stop(self):
        """Stop and join the updater thread.
        """
        self.thread.stop()
        self.thread.join()

    def is_running(self):
        """Is the updater thread still running?
        """
        return self.thread.is_running()


def start_display_refresh(params: dict):
    """Create the TickerUpdater object if it doesn't exist.

    Create the updater object, which creates the updater thread.
    The thread checks the value of 'next_update' from the quote
    cache to determine whether data needs refreshing.

    Args:
      params:
        The value of g:ticker_parameters.
    """
    global UPDATER
    if UPDATER is None:
        UPDATER = TickerUpdater(params)
        while not UPDATER.is_running():
            time.sleep(0.01)


def stop_display_refresh():
    """Stop the TickerUpdater object if it exists.

    Wait for the updater thread to stop, then destroy the object.
    """
    global UPDATER
    if UPDATER is not None:
        UPDATER.stop()
        del UPDATER
        UPDATER = None


if __name__ == '__main__':
    #     'c'         'd'         'p'          'h'
    #     'l'         'o'          'C'
    q = { 'c': 47.08, 'd': 1.32, 'dp': 2.8846, 'h': 47.116,
          'l': 46.02, 'o': 46.48, 'pc': 45.76, 't': 1703192401 }

    p = FmtStringParser()
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

    #params = {
    #  'rest_api_key': 'blah',
    #  'refresh_interval_minutes': 120,
    #  'quote_cache_file': '/home/tswhison/.vim/ticker/ticker_cache.json',
    #}
    #start_display_refresh(params)
    #time.sleep(5 * 60.0)
    #stop_display_refresh(params)
