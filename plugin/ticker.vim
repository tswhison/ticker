
if version < 802
  echohl WarningMsg
  echom  "ticker requires Vim >= 8.2.0"
  echohl None
  finish
endif

if !has("python3")
  echohl WarningMsg
  echo "Compile Vim with +python3 to use this plugin."
  echohl None
  finish
endif

if exists('g:ticker_plugin_loaded')
  finish
endif
let g:ticker_plugin_loaded = 1

let s:plugin_root_dir = fnamemodify(resolve(expand('<sfile>:p')), ':h')

python3 << EOF
import sys
from os.path import normpath, join
import vim
plugin_root_dir = vim.eval('s:plugin_root_dir')
python_root_dir = normpath(join(plugin_root_dir, '..', 'python'))
sys.path.insert(0, python_root_dir)
import ticker
EOF

" Find REST API Key if not already defined.
if !exists('g:ticker_rest_api_key')
  " Search for it in the environment.
  let s:env = environ()
  if has_key(s:env, 'TICKER_REST_API_KEY')
    let g:ticker_rest_api_key = s:env['TICKER_REST_API_KEY']
  endif
  unlet s:env
  " Read it from file.
  if !exists('g:ticker_rest_api_key') && exists('g:ticker_rest_api_key_file')
    let s:lines = readfile(g:ticker_rest_api_key_file, '', 1)
    let g:ticker_rest_api_key = s:lines[0]
    unlet s:lines
  endif
endif

" Default portfolio when not defined otherwise.
if !exists('g:ticker_portfolio')
  let g:ticker_portfolio = {
  \ 'GOOGL': '%5t $%-6.2c (%-5.2p%%)',
  \ 'META': '%5t $%-6.2c (%-5.2p%%)',
  \ 'AMZN': '%5t $%-6.2c (%-5.2p%%)',
  \ 'AAPL': '%5t $%-6.2c (%-5.2p%%)',
  \ 'NFLX': '%5t $%-6.2c (%-5.2p%%)',
  \}
endif

" Quotes are refreshed after this number of minutes,
" when the display is active.
if !exists('g:ticker_refresh_interval_minutes')
  let g:ticker_refresh_interval_minutes = 120
endif
if !exists('g:ticker_quote_cache_file')
  let g:ticker_quote_cache_file = expand('~/.vim/ticker/ticker_cache.json')
endif

" Colors for displaying gain/loss.
if !exists('g:ticker_up_highlight')
  let g:ticker_up_highlight = 'ctermbg=Green ctermfg=White'
endif
if !exists('g:ticker_down_highlight')
  let g:ticker_down_highlight = 'ctermbg=Red ctermfg=Gray'
endif

exe 'highlight tickerUpHi ' . g:ticker_up_highlight
exe 'highlight tickerDownHi ' . g:ticker_down_highlight

" Where to position the display in the parent window.
if !exists('g:ticker_location')
  " g:ticker_location has two forms. The first is a string,
  " which may have the values 'topleft', 'topright', 'botleft',
  " 'botright', or 'center'.
  " The second form of g:ticker_location is a list of two
  " integers, specifying the col and row of an absolute
  " window position in that order: eg,
  " let g:ticker_location = [3, 5] means x,y == 3,5.
  let g:ticker_location = 'topright'
endif

let g:ticker_parameters = {
\  'rest_api_key': g:ticker_rest_api_key,
\  'refresh_interval_minutes': g:ticker_refresh_interval_minutes,
\  'quote_cache_file': g:ticker_quote_cache_file,
\}

function! ticker#RefreshQuoteDataNow()
  py3 ticker.refreshQuoteDataNow(vim.eval('g:ticker_parameters'), vim.eval('g:ticker_portfolio'))
  " If we're currently displaying, then force a refresh.
  if ticker#IsDisplaying()
    call ticker#_Hide()
    call ticker#_Display()
  endif
endfunction

function! ticker#GetTickerDisplayData()
  " Convert g:ticker_portfolio into a display data structure
  let g:ticker_display_data = {}
  py3 vim.command("let g:ticker_display_data = %s" % (ticker.getTickerData(vim.eval('g:ticker_parameters'), vim.eval('g:ticker_portfolio'))))
  return g:ticker_display_data
endfunction

let g:ticker_popup_winids = []

function! ticker#IsDisplaying()
  return len(g:ticker_popup_winids) > 0
endfunction

function! ticker#Display()
  if ticker#IsDisplaying()
    " Nothing to do.
    return
  endif

  call ticker#_Display()

  py3 ticker.startDisplayRefresh(vim.eval('g:ticker_parameters'))
endfunction

function! ticker#_Display()
  let parentwidth = winwidth(0)
  let parentheight = winheight(0)

  " Read the display data, possibly from cache.
  let disp = ticker#GetTickerDisplayData()

  " Determine the max width of a display string.
  let maxwidth = 0
  for k in keys(disp)
    let w = strwidth(k)
    if w > maxwidth
      let maxwidth = w
    endif
  endfor

  " The display can't be wider than the parent window.
  if maxwidth > parentwidth
    let maxwidth = parentwidth
  endif

  " Cap the display height at max of parentheight,
  " number of display items.
  let maxheight = parentheight
  if maxheight > len(keys(disp))
    let maxheight = len(keys(disp))
  endif

  let col = 0
  let line = 0

  " Use g:ticker_location together with maxwidth and
  " maxheight to determine the starting col,line pair.
  if type(g:ticker_location) == v:t_string
    if g:ticker_location == 'topleft'
      let col = 0
      let line = 0
    elseif g:ticker_location == 'topright'
      let col = parentwidth - maxwidth
      let line = 0
    elseif g:ticker_location == 'botleft'
      let col = 0
      let line = parentheight - maxheight
    elseif g:ticker_location == 'botright'
      let col = parentwidth - maxwidth
      let line = parentheight - maxheight
    elseif g:ticker_location == 'center'
      let col = (parentwidth / 2) - (maxwidth / 2)
      let line = (parentheight / 2) - (maxheight / 2)
    endif
    let col += 1
    let line += 1
  elseif type(g:ticker_location) == v:t_list
    let col = g:ticker_location[0]
    let line = g:ticker_location[1]
  else
    " Error case: fail back to upper left.
    let col = 1
    let line = 1
  endif

  for k in keys(disp)
    if line > parentheight
      return
    endif

    let text = k
    let opts = {
     \ 'line': line,
     \ 'col' : col,
     \ 'maxheight': 1,
     \ 'minheight': 1,
     \ 'maxwidth': maxwidth,
     \ 'minwidth': maxwidth,
     \}
    if disp[k]
      let color = 'tickerUpHi'
    else
      let color = 'tickerDownHi'
    endif

    let winid = popup_create(text, opts)
    call setwinvar(winid, '&wincolor', color)
    call add(g:ticker_popup_winids, winid)

    let line += 1
  endfor
endfunction

function ticker#Hide()
  if !ticker#IsDisplaying()
    " Nothing to do.
    return
  endif

  py3 ticker.stopDisplayRefresh(vim.eval('g:ticker_parameters'))

  call ticker#_Hide()
endfunction

function! ticker#_Hide()
  " Close each of the display popups.
  for winid in g:ticker_popup_winids
    call popup_close(winid)
  endfor

  " Popups are destroyed.
  let g:ticker_popup_winids = []
endfunction

function! ticker#Toggle()
  if ticker#IsDisplaying()
    call ticker#Hide()
  else
    call ticker#Display()
  endif
endfunction

autocmd VimLeavePre * call ticker#Hide()

"nnoremap <c-t> :call ticker#Toggle() <CR>
"nnoremap <c-r> :call ticker#RefreshQuoteDataNow() <CR>
