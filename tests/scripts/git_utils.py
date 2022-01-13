import json
import subprocess
import re
from urllib import request
from typing import Dict, Tuple, Any


class GitHubRepo:
    def __init__(self, user, repo, token):
        self.token = token
        self.user = user
        self.repo = repo
        self.base = f"https://api.github.com/repos/{user}/{repo}/"

    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
        }

    def graphql(self, query: str) -> Dict[str, Any]:
        return self._post("https://api.github.com/graphql", {"query": query})

    def _post(self, full_url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        print("Requesting", full_url)
        req = request.Request(full_url, headers=self.headers(), method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        data = json.dumps(body)
        data = data.encode("utf-8")
        req.add_header("Content-Length", len(data))

        with request.urlopen(req, data) as response:
            response = json.loads(response.read())
        return response

    def post(self, url: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(self.base + url, data)

    def get(self, url: str) -> Dict[str, Any]:
        url = self.base + url
        print("Requesting", url)
        req = request.Request(url, headers=self.headers())
        with request.urlopen(req) as response:
            response = json.loads(response.read())
        return response

    def delete(self, url: str) -> Dict[str, Any]:
        url = self.base + url
        print("Requesting", url)
        req = request.Request(url, headers=self.headers(), method="DELETE")
        with request.urlopen(req) as response:
            response = json.loads(response.read())
        return response


def parse_remote(remote: str) -> Tuple[str, str]:
    """
    Get a GitHub (user, repo) pair out of a git remote
    """
    if remote.startswith("https://"):
        # Parse HTTP remote
        parts = remote.split("/")
        if len(parts) < 2:
            raise RuntimeError(f"Unable to parse remote '{remote}'")
        return parts[-2], parts[-1].replace(".git", "")
    else:
        # Parse SSH remote
        m = re.search(r":(.*)/(.*)\.git", remote)
        if m is None or len(m.groups()) != 2:
            raise RuntimeError(f"Unable to parse remote '{remote}'")
        return m.groups()


def git(command):
    command = ["git"] + command
    print("Running", command)
    proc = subprocess.run(command, stdout=subprocess.PIPE, check=True)
    return proc.stdout.decode().strip()
