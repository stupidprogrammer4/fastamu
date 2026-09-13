from papilio.infra.http.gateway import BaseGateway


class <<P>>Gateway(BaseGateway):
    """Outbound calls for the <<S>> module.

    Map the response into this module's own domain types before returning —
    nothing above infra/ should be reading a third party's JSON shape.
    """

    __base_url__ = ""

    async def fetch(self, path: str) -> dict:
        resp = await self.get(path)
        resp.raise_for_status()
        return resp.json()
