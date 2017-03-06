import asyncio
import datetime
import hashlib
import io
import time
from collections import namedtuple
from contextlib import redirect_stdout
from typing import Iterable

from aiohttp import ClientSession
from aiohttp import web
from aiohttp.web import Application, StreamResponse, run_app, Request, Response

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
DEFAULT_TTL = 60 * 60 * 24


class Store:
    _cache = {}
    _expires = {}
    _max_objects = 100

    async def set(self, key: bytes, value: object, ttl: int = DEFAULT_TTL):
        self._cache[key] = value
        self._expires[key] = time.time() + ttl
        return value

    async def get(self, key: bytes) -> None or object:
        value = self._cache.get(key, None)

        if value is None:
            return

        exp = self._expires.get(key, -1)

        print(exp, '>', time.time())

        if exp is None or exp <= time.time():
            del self._cache[key]
            del self._expires[key]
            return None

        return value


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


def hash_request(request: Request) -> bytes:
    sha1 = hashlib.sha1()
    sha1.update(request.method.encode())
    sha1.update(str(request.rel_url).encode())
    return sha1.digest()


store = Store()

ItemResponse = namedtuple('ItemResponse', ['status', 'reason', 'method', 'url', 'headers', 'body'])


async def relay_stream(request: Request):
    host, port = request.rel_url.path.split(':')
    port = int(port)
    reader, writer = await asyncio.open_connection(
        host=host, port=port, ssl=True)

    while True:
        await writer.drain()

        data = await reader.read(1024 * 1024)
        if not data:
            break
        print('received data', data)
        writer.write(data)
        await writer.drain()

    writer.close()


async def proxy_handler(request: Request):
    hash_key = hash_request(request)
    response = await store.get(hash_key)
    loop = asyncio.get_event_loop()

    if request.method == 'CONNECT':
        asyncio.ensure_future(relay_stream(request), loop=loop)

        return Response(status=200,
                        reason='Connection Established',
                        headers={'Proxy-agent': 'aioproxy'})

    if response:
        print('HIT')
        stream = StreamResponse(status=response.status, reason=response.reason, headers=response.headers)
        stream.headers['X-Cache'] = 'HIT'

        await stream.prepare(request)
        stream.write(response.body)

        return stream
    else:

        with ClientSession() as session:
            headers = request.headers.copy()

            async with session.request(request.method, request.rel_url, headers=headers) as resp:
                response = ItemResponse(resp.status,
                                        resp.reason,
                                        request.method,
                                        request.rel_url,
                                        headers,
                                        await resp.read())

                loop.create_task(store.set(hash_key, response))

                stream = StreamResponse(status=response.status, reason=response.reason, headers=response.headers)
                stream.headers['X-Cache'] = 'Miss'

                await stream.prepare(request)
                stream.write(response.body)

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
