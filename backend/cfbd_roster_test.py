import requests, os, pandas as pd
from dotenv import load_dotenv
load_dotenv()

# resp = requests.get(
#     "https://api.collegefootballdata.com/roster",
#     params={"team": "Florida State", "year": 2026},
#     headers={"Authorization": f"Bearer {os.environ['CFBD_API_KEY']}"}
# )

resp = requests.get(
    "https://api.collegefootballdata.com/roster",
    params={"team": "Florida State", "year": 2025},
    headers={"Authorization": f"Bearer {os.environ['CFBD_API_KEY']}"}
)
df = pd.DataFrame(resp.json())
print(f"Total: {len(df)}")
print(df.columns.tolist())




df = pd.DataFrame(resp.json())
print(f"Total players: {len(df)}")
print("\nPosition counts:")
print(df["position"].value_counts().to_string())
print("\nSample CB:")
print(df[df["position"] == "CB"][["id", "first_name", "last_name", "position", "year"]].head(5).to_string())