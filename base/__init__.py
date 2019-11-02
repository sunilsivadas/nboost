from ..cli import set_logger
from multiprocessing import Process, Event
from aiohttp import web, web_exceptions
import copy
import asyncio
import pprint


class Response:
    @staticmethod
    def json_200(response: dict):
        return web.json_response(response, status=200)

    @staticmethod
    def plain_200(response: bytes):
        return web.Response(body=response, status=200)

    @staticmethod
    def status_404():
        return web.json_response(status=404)

    @staticmethod
    def exception_500(ex: Exception):
        return web.json_response(dict(error=str(ex), type=type(ex).__name__), status=500)


class RouteHandler:
    def __init__(self, rh: 'RouteHandler' = None):
        self.routes = copy.deepcopy(rh.routes) if rh else []

    def add_route(self, method, path):
        def decorator(f):
            self.routes += [(method, path, f)]
            return f
        return decorator

    def bind_routes(self, obj):
        return [web.route(method, path, getattr(obj, f.__name__)) for method, path, f in self.routes]


class BaseProcess(Process):
    def __new__(cls, **kwargs):
        cls.logger = set_logger(cls.__name__)
        cls.logger.info(cls._format_kwargs(kwargs))
        return super().__new__(cls)

    @classmethod
    def _format_kwargs(cls, kwargs):
        return ''.join([cls._format_kwarg(k, v) for k, v in kwargs.items()])

    @staticmethod
    def _format_kwarg(k, v):
        switch = k[:14], ' '*(15 - len(k)), v, v.__class__.__name__
        return '\n--%s%s%s (%s)' % switch

    def _run(self):
        raise NotImplementedError

    def run(self):
        try:
            self._run()
        except Exception as ex:
            self.logger.error(ex, exc_info=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class BaseServer(BaseProcess):
    handler = RouteHandler()

    def __init__(self, host: str = '127.0.0.1', port: int = 53001, **kwargs):
        super().__init__()
        self.host = host
        self.port = port
        self.url = 'http://%s:%s' % (host, port)
        self.is_ready = Event()

    async def not_found_handler(self, request: 'web.BaseRequest'):
        raise web_exceptions.HTTPNotFound

    @web.middleware
    async def middleware(self, request: 'web.BaseRequest', handler) -> 'web.Response':
        try:
            self.logger.info(request)
            response = await handler(request)

        except web_exceptions.HTTPNotFound:
            response = await self.not_found_handler(request)

        except Exception as ex:
            self.logger.error(ex, exc_info=True)
            response = Response.exception_500(ex)

        self.logger.info(response)
        return response

    def _run(self):
        loop = asyncio.get_event_loop()
        routes = self.handler.bind_routes(self)

        async def create_site():
            app = web.Application(middlewares=[self.middleware])
            app.add_routes(routes)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, self.host, self.port)
            await site.start()
            self.logger.critical('listening on  %s:%d' % (self.host, self.port))
            self.is_ready.set()

        loop.run_until_complete(create_site())
        loop.run_forever()

