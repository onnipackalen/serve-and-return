"""Parse a Tennis Abstract jsfrags player file into match rows."""
import re, html, sys

ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG = re.compile(r"<[^>]+>")

def text(s):
    return html.unescape(TAG.sub("", s)).strip()

def parse(path):
    h = open(path, encoding="utf-8", errors="replace").read()
    i = h.find('id="recent-results"')
    if i < 0:
        return []
    j = h.find("</table>", i)
    body = h[i:j]
    out = []
    for m in ROW.finditer(body):
        cells = CELL.findall(m.group(1))
        if len(cells) < 15:
            continue
        raw = [text(c) for c in cells]
        # score cell keeps the opponent link; grab the opponent name from it
        opp = re.search(r"player\.cgi\?p=([A-Za-z0-9]+)", cells[6])
        out.append({"date": raw[0], "tourney": raw[1], "surface": raw[2],
                    "round": raw[3], "rk": raw[4], "vrk": raw[5],
                    "result": raw[6], "score": raw[7], "dr": raw[8],
                    "ace_pct": raw[9], "df_pct": raw[10], "first_in": raw[11],
                    "first_pct": raw[12], "second_pct": raw[13],
                    "bpsvd": raw[14], "time": raw[15] if len(raw) > 15 else "",
                    "opp_key": opp.group(1) if opp else ""})
    return out

if __name__ == "__main__":
    rows = parse(sys.argv[1])
    print(f"{len(rows)} rows")
    print("date range:", rows[-1]["date"], "->", rows[0]["date"])
    for r in rows[:3]:
        print(r)
