import requests
from bs4 import BeautifulSoup
import urllib.parse
import time

def check_bing_vacancy(company_name, keyword):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    queries = [
        f'site:linkedin.com/jobs/ "{company_name}" "{keyword}"',
        f'site:indeed.com/q- "{company_name}" "{keyword}"',
        f'"{company_name}" ("careers" OR "jobs" OR "hiring") "{keyword}"'
    ]
    
    for q in queries:
        url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(q)}"
        print(f"Querying Bing: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Status Code: {response.status_code}")
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Check for organic search results
                links = []
                for a in soup.select("li.b_algo h2 a"):
                    href = a.get("href")
                    if href:
                        links.append(href)
                        
                print(f"Extracted {len(links)} links:")
                for l in links[:3]:
                    print(f" - {l}")
                    
                if links:
                    return links[0]
            time.sleep(2)
        except Exception as e:
            print(f"Error: {e}")
            
    return None

if __name__ == "__main__":
    check_bing_vacancy("Codegnan", "developer")
