"""Build agent_sheet_requests.md from the five ReproChem requests."""
from reprochem_requests import REQUESTS
from workflow_or_agent import review, to_markdown

if __name__ == "__main__":
    rows = review(REQUESTS)
    md = to_markdown(rows, "ReproChem · Workflow or agent? Five real requests")
    open("agent_sheet_requests.md", "w").write(md)
    print(md)
    bad = [r["n"] for r in rows if not r["agrees"]]
    print("Checklist disagrees on:", bad or "none")
