Ticker: track your stock portfolio in Vim
=========================================

Ticker is a Vim plugin that allows you to track your stock portfolio
directly in your current Vim window, because.. Why not?
Ticker uses [Vim's popup support](https://vimhelp.org/popup.txt.html),
which was added in Vim 8.2, and the Vim [Python bindings](https://vimhelp.org/if_pyth.txt.html).
To provide the stock data, Ticker uses the [Finnhub](https://finnhub.io)
REST API for Python, which requires a [Finnhub API key](https://finnhub.io/register).

Installation
------------

### vim-plug

To install Ticker using [vim-plug](https://github.com/junegunn/vim-plug),
add the following lines to your `~/.vimrc`:

``` vim
call plug#begin()
  Plug 'tswhison/ticker'
call plug#end()
```

Then, run the following command to install Ticker:

``` vim
:PlugInstall
```

### Python

Next, install the Finnhub Python module by issuing the following
command from the shell:

``` bash
$ pip3 install finnhub-python
```

### Key Bindings

Following is an example of some useful Vim key bindings for Ticker.
These bindings toggle Ticker display on/off and force a data refresh,
using Ctrl+t and Ctrl+r, respectively.

``` vim
nnoremap <c-t> :call ticker#Toggle() <CR>
nnoremap <c-r> :call ticker#RefreshQuoteDataNow() <CR> 
```

Configuration
-------------

### Finnhub API key

Ticker retrieves stock quotes using the Finnhub REST API for Python,
and it provides three ways to configure your API key. Select the method
that works best for you:

#### Method 0) Vim variable

Declare a global variable in your `~/.vimrc`

``` vim
let g:ticker_rest_api_key = 'my api key'
```

** Note ** when using this method, be sure to protect your key
with the appropriate file permissions. Use with caution.

#### Method 1) Environment variable

You can pass the REST API key as an environment variable when
starting Vim:

``` bash
$ TICKER_REST_API_KEY='my api key' vim myfile.txt
```

** Note ** when using this method, your API key will appear
in the shell's command history. Use with caution.

#### Method 2) Key file

You can store the REST API key in a secured location on disk,
then tell Ticker where to find your key file, eg via `~/.vimrc`:

``` vim
let g:ticker_rest_api_key_file = expand('~/.vim/myapikey.txt')
```

### Stock Portfolio

Ticker provides a default stock portfolio via the Vim dictionary
variable `g:ticker_portfolio`. Each entry in the dictionary maps
a ticker symbol to a format string used to format the display output
for that symbol.

In order to customize Ticker to display your stock portfolio, define
`g:ticker_portfolio` in your `~/.vimrc` prior to the line that loads
the Ticker plugin.

Example:

``` vim
let g:ticker_portfolio = {
\ 'MYSTOCKA': '%8t $%-6.2c',
\ 'MYSTOCKB': '%8t $%-6.2c',
\}
```

In the example, Ticker is configured to display a portfolio consisting
of two stock symbols, MYSTOCKA and MYSTOCKB. The output of each stock
quote consists of the ticker symbol formatted within the first eight
columns of its display window (`%8t`), together with the current stock
price formatted in a field width of six columns, right justified, with
two digits of precision (`$%-6.2c`).

As you can see, Ticker allows you to fully customize exactly what it
displays on your screen. The following format codes and their meanings
are provided to allow you to customize the look and feel to your liking:

| Format Specifier | Meaning |
| ---------------- | ------- |
| %t | Stock Ticker Symbol |
| %c | Current price |
| %d | Day's change  |
| %p | Day's percentage change |
| %h | High price of the day |
| %l | Low price of the day |
| %o | Open price of the day |
| %C | Previous day's closing price |
| %% | The % character |

#### Display Colors

Ticker automatically changes the colors of the display area via two
global Vim variables that have the following default implementation.
To override the color scheme, you can define these variables in
`~/.vimrc` prior to the line that loads the Ticker plugin:

``` vim
let g:ticker_up_highlight = 'ctermbg=Green ctermfg=White'
let g:ticker_down_highlight = 'ctermbg=Red ctermfg=Gray'
```

If a stock's `%p` is less than 0.0, then `g:ticker_down_highlight`
is used; otherwise `g:ticker_up_highlight` is used when coloring
the display content.

#### Popup Location

Ticker allows you to provide either a relative window location
string, for example 'topleft'; or an absolute coordinate, [1, 1].
The default value of `g:ticker_location` is 'topright'. You can
override this by assigning a value to `g:ticker_location` in your
`~/.vimrc`.

| String | Window Relative Location |
| ------ | ------------------------ |
| 'topleft'  | Upper left corner |
| 'topright' | Upper right corner |
| 'botleft'  | Lower left corner |
| 'botright' | Lower right corner |
| 'center' | Center of window |

| List | Window Absolute Location |
| ---- | ------------------------ |
| [3, 5] | column 3, line 5 |

#### Refresh Interval & Quote Cache File

When Ticker is visible on the screen, the stock quote data is
refreshed every two hours by default. You can override this default
setting by defining `g:ticker_refresh_interval_minutes` in your
`~/.vimrc`. As the variable name indicates, the units are minutes
between refreshes.

Ticker tracks the stock quote data for your portofolio by caching
it in a local file, the quote cache file. The quote cache file contains
a timestamp when the next data refresh will occur.

When Ticker is actively displaying, it examines this timestamp in
order to know when a data refresh is required. When the refresh
time is reached, Ticker uses the Finnhub REST API to request new
quote data for each ticker symbol, storing the new data along with
a new timestamp in the quote cache file.

When Ticker is not active, for example if Ticker is not displaying
or Vim is closed, no data refreshes occur. The next time Vim starts
and loads Ticker, Ticker examines the timestamp in the quote cache
file, comparing it to the current time. If the timestamp from the
quote cache file has passed, then Ticker refreshes the quote data
for all ticker symbols.

To override the location of the quote cache file, define
`g:ticker_quote_cache_file` in your `~/.vimrc`. The default definition
is:

``` vim
let g:ticker_quote_cache_file = expand('~/.vim/ticker/ticker_cache.json')
```

#### Bug Reports

Please file any bug reports and suggestions for improvement.

#### Disclaimer

Finnhub and Vim are property of their respective owners. I claim no rights to
either of these technologies.
