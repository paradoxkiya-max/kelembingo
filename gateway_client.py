import os
import requests
import logging

logger = logging.getLogger(__name__)

class GatewayDocSnapshot:
    def __init__(self, doc_id: str, data: dict, exists: bool):
        self.id = str(doc_id)
        self._data = data or {}
        self.exists = exists

    def to_dict(self):
        return self._data

    def get(self, field, default=None):
        return self._data.get(field, default)


class GatewayDocRef:
    def __init__(self, collection: str, doc_id: str, gateway_url: str, api_key: str = ""):
        self.collection = collection
        self.id = str(doc_id)
        self.doc_id = str(doc_id)
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-Internal-Key"] = self.api_key
        return h

    def get(self):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("data", {})
                return GatewayDocSnapshot(self.id, data, True)
            return GatewayDocSnapshot(self.id, {}, False)
        except Exception as e:
            logger.error(f"GatewayDocRef get error for {self.collection}/{self.id}: {e}")
            return GatewayDocSnapshot(self.id, {}, False)

    def set(self, data, merge=False):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        try:
            r = requests.post(url, json={"data": data, "merge": merge}, headers=self._headers(), timeout=10)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"GatewayDocRef set error for {self.collection}/{self.id}: {e}")

    def update(self, data):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        try:
            r = requests.patch(url, json={"data": data}, headers=self._headers(), timeout=10)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"GatewayDocRef update error for {self.collection}/{self.id}: {e}")

    def delete(self):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        try:
            requests.delete(url, headers=self._headers(), timeout=10)
        except Exception as e:
            logger.error(f"GatewayDocRef delete error for {self.collection}/{self.id}: {e}")


class GatewayCollectionRef:
    def __init__(self, collection: str, gateway_url: str, api_key: str = "", filters=None, order_by=None, order_dir="ASCENDING", limit_n=None):
        self.collection = collection
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self._filters = filters or []
        self._order_by = order_by
        self._order_dir = order_dir
        self._limit_n = limit_n

    def document(self, doc_id: str):
        return GatewayDocRef(self.collection, str(doc_id), self.gateway_url, self.api_key)

    def doc(self, doc_id: str):
        return self.document(doc_id)

    def where(self, field, op, value):
        new_filters = list(self._filters) + [[field, op, value]]
        return GatewayCollectionRef(self.collection, self.gateway_url, self.api_key, filters=new_filters, order_by=self._order_by, order_dir=self._order_dir, limit_n=self._limit_n)

    def order_by(self, field, direction="ASCENDING"):
        return GatewayCollectionRef(self.collection, self.gateway_url, self.api_key, filters=self._filters, order_by=field, order_dir=direction, limit_n=n)

    def limit(self, n):
        return GatewayCollectionRef(self.collection, self.gateway_url, self.api_key, filters=self._filters, order_by=self._order_by, order_dir=self._order_dir, limit_n=n)

    def get(self):
        url = f"{self.gateway_url}/api/db/{self.collection}"
        params = {}
        if self._filters:
            import json
            params["filters"] = json.dumps(self._filters)
        if self._order_by:
            params["order_by"] = self._order_by
            params["order_dir"] = self._order_dir
        if self._limit_n:
            params["limit_n"] = self._limit_n
        headers = {}
        if self.api_key:
            headers["X-Internal-Key"] = self.api_key
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            if r.status_code == 200:
                docs = r.json()
                return [GatewayDocSnapshot(d.get("id"), d.get("data", {}), True) for d in docs]
            return []
        except Exception as e:
            logger.error(f"GatewayCollectionRef get error for {self.collection}: {e}")
            return []


class GatewayClient:
    def __init__(self, gateway_url: str = None, api_key: str = None):
        self.gateway_url = (gateway_url or os.getenv("GATEWAY_URL", "https://kelembingo-gateway-gjfl.onrender.com")).rstrip("/")
        self.api_key = api_key or os.getenv("INTERNAL_API_KEY", "")

    def collection(self, name: str):
        return GatewayCollectionRef(name, self.gateway_url, self.api_key)
