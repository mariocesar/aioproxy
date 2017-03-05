import asyncio
import datetime
import io
import hashlib
from contextlib import redirect_stdout
from typing import Iterable
import time

import aiohttp
from aiohttp import ClientSession
from aiohttp import web
from aiohttp.web import Application, StreamResponse, run_app, Response

START = time.time()

render_webpage = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>aioProxy</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            font-size: 14px;
            line-height: 1.5;
            color: #333;
            background-color: #fff;
            margin: 0 1rem;
            word-wrap: break-word;
        }}
        @media screen and (min-width: 980px) {{
            body {{
                margin: 0
            }}
        }}
        a:visited {{
            color: #9B59B6;
        }}
        a {{
            color: #2980B9;
            text-decoration: none;
            cursor: pointer;
        }}
        a:hover {{
            color: #3091d1;
        }}
        footer {{
            margin-top: 1rem;
            margin-bottom: 1rem;
            font-color: #CCC;
        }}
        .container {{
            margin-right: auto;
            margin-left: auto;
        }}
        @media screen and (min-width: 980px) {{
            .container {{
                width: 980px;
            }}
        }}
        .module {{
            margin-top: 1rem;
            border: 1px solid #dfe2e5;
            border-radius: 3px;
        }}
        table.files {{
            width: 100%;
            background: #fff;
            border-radius: 2px
        }}
        table.files td {{
            padding: 6px 3px;
            line-height: 20px;
            border-top: 1px solid #eaecef
        }}
        table.files td:first-child {{
            max-width: 180px
        }}
        table.files td {{
            max-width: 442px;
            padding-left: 10px;
            overflow: hidden;
            color: #6a737d
        }}
        table.files td a {{
            color: #6a737d
        }}
        table.files td a:hover {{
            color: #0366d6
        }}
        table.files td:last-child {{
            width: 125px;
            padding-right: 10px;
            color: #6a737d;
            text-align: right;
            white-space: nowrap
        }}
        table.files tbody tr:first-child td {{
            border-top: 0
        }}
        .title {{
            font-weight: bold;
        }}
        header {{
            font-size: 1.12rem;
            line-height: 4rem;
        }}
    </style>
  </head>
  <body>
  <div class="container">
  <header>
    <a class="title">aioproxy</a> {header}
  </header>
  {body}
  <footer>
  Buil with Python3, aiohttp and Love. by <a href="https://twitter.com/mariocesar_bo">@mariocesar_bo</a>
  </footer>
  </div>
  </body>
</html>
""".format


def hash_request(request):
    sha1 = hashlib.sha1()
    sha1.update(request)
    return sha1.hexdigest()


def curl(url):
    session = ClientSession()
    response = yield from session.request('GET', url)

    print(repr(response))

    chunk = yield from response.content.read()
    print('Downloaded: %s' % len(chunk))

    response.close()
    yield from session.close()


def render_table(rows: Iterable) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        print('<div class="module">')
        print("""<table class="files"><tbody>""")

        for row in rows:
            print("<tr>")
            for cell in row:
                print("<td>{}</td>".format(cell))
            print("</tr>")

        print("</tbody></table>")
        print("</div>")

    return out.getvalue()


async def landing_view(request):
    rows = map(lambda n: (n, n, n), range(10))
    delta = datetime.timedelta(seconds=time.time() - START)
    binary = render_webpage(
        header=f'uptime: {delta}',
        body=render_table(rows)
    ).encode('utf8')
    resp = StreamResponse()
    resp.content_length = len(binary)
    resp.content_type = 'text/html'
    await resp.prepare(request)
    resp.write(binary)
    return resp


async def proxy_handler(request):
    headers = request.headers.copy()
    headers['Via'] = 'aioproxy'
    async with ClientSession() as session:
        async with session.request(request.method, request.rel_url, headers=headers) as resp:
            stream = StreamResponse(status=resp.status, reason=resp.reason, headers=headers)
            await stream.prepare(request)
            async for data in resp.content.iter_chunked(1024):
                stream.write(data)
    return stream


async def init_proxy(loop):
    server = web.Server(proxy_handler)
    await loop.create_server(server, "0.0.0.0", 8080)
    print("======= Serving proxy http://0.0.0.0:8080/ ======")


async def init_web(loop):
    app = Application(loop=loop)
    app.router.add_get('/', landing_view)

    return app


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    proxy = loop.run_until_complete(init_proxy(loop))
    app = loop.run_until_complete(init_web(loop))
    run_app(app, host='127.0.0.1', port=8000)
