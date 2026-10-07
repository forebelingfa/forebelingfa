import time
import hashlib
import json
import requests
from typing import Dict, List, Optional

class DazzH5Client:
    BASE_URL = "https://h5.idlive.xin/api/"
    SECRET_KEY = "5d206b343f87f2ca3a0aa05c58b9a64d"
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36"

    def __init__(self, session: Optional[requests.Session] = None, user_agent: str = ""):
        self.session = session or requests.Session()
        self.ua = user_agent or self.DEFAULT_USER_AGENT
        # Store initialization context found during GET request
        self.h5_context: Dict = {
            "package_name": "app.dazz.live",
            "version": "1.9.9",
            "channel_id": "3"
        }

    def _generate_sign(self, payload: Dict) -> str:
        """Standard Dazz MD5 signing logic for H5."""
        filtered = {k: v for k, v in payload.items() if k not in ["sign", "CREATOR", "serialVersionUID"]}
        sorted_items = sorted(filtered.items())
        
        param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
        full_string = f"{param_str}&key={self.SECRET_KEY}"
        
        return hashlib.md5(full_string.encode("utf-8")).hexdigest()

    def _post(self, endpoint: str, payload: Dict, include_context: bool = True) -> Dict:
        """Centralized POST handler for H5 endpoints."""
        url = f"{self.BASE_URL}{endpoint}"
        
        # Merge necessary context if required (usually true for signed API calls)
        if include_context:
            payload.update(self.h5_context)

        # Generate timestamp and sign immediately before sending
        current_time = str(int(time.time()))
        payload["time"] = current_time
        payload["sign"] = self._generate_sign(payload)

        headers = {
            "User-Agent": self.ua,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://h5.idlive.xin",
            "Referer": "https://h5.idlive.xin/",
            "X-Requested-With": "app.dazz.live"
        }

        try:
            resp = self.session.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            return {"code": -1, "msg": f"HTTP Request Failed: {e}"}
        except json.JSONDecodeError:
            return {"code": -2, "msg": "Failed to decode JSON response"}


    # --- API Methods ---

    def init_signtask_page(self, user_id: str, token: str) -> requests.Response:
        """Initial GET request to the task page (useful for cookies/initialization)."""
        url = "https://h5.idlive.xin/task/signtask"
        params = {
            "user_id": user_id, "token": token, "in_room": "0", "channel_id": "3",
            "package_name": "app.dazz.live", "version": "1.9.9", "language": "id"
        }
        response = self.session.get(url, params=params, headers={"User-Agent": self.ua}, timeout=10)
        
        # IMPORTANT: If the API uses cookies from this GET for authentication on subsequent POSTs, 
        # they are now stored in self.session.
        
        return response

    def check_login(self, user_id: str, token: str) -> Dict:
        # This endpoint seems to require minimal payload (just user identifiers)
        return self._post("go_v3/hg/h5/loginstatus", {"user_id": user_id, "token": token, "lang": "id"}, include_context=False)

    def sign_in(self, user_id: str, token: str, sign_type: int = 1) -> Dict:
        # Ensure 'lang' is always passed as the JS code does it
        return self._post("go_v3/dazz/h5/sign", {"user_id": user_id, "token": token, "type": sign_type, "lang": "id"})

    def get_task_list(self, user_id: str, token: str) -> Dict:
        return self._post("go_v3/dazz/h5/task_list", {"user_id": user_id, "token": token, "task_type": "1,10", "lang": "id"})

    def apply_task(self, user_id: str, token: str, task_id: int) -> Dict:
        return self._post("go_v3/dazz/h5/task_apply", {"user_id": user_id, "token": token, "task_id": task_id, "lang": "id"})

    def open_box(self, user_id: str, token: str, box_id: int) -> Dict:
        return self._post("go_v3/dazz/h5/open_box", {"user_id": user_id, "token": token, "box_type": 1, "box_id": box_id, "lang": "id"})

    # --- Composite Workflow ---

    def run_daily_workflow(self, user_id: str, token: str) -> Dict:
        """Runs the standard sequence: login -> signs -> apply tasks -> open boxes."""
        results = {"user_id": user_id, "actions": [], "errors": []}
        
        # 1. Initialization / Session Setup
        init_response = self.init_signtask_page(user_id, token)
        results["actions"].append(f"Init Page Call Status: {init_response.status_code}")
        if init_response.status_code != 200:
             results["errors"].append(f"Initialization GET failed with status: {init_response.status_code}")
             return results

        # 2. Login Check (Modified to exclude context as it often requires cleaner payload)
        login = self.check_login(user_id, token)
        if login.get("code") != 0:
            results["errors"].append(f"Login Check Failed (Code {login.get('code')}): {login.get('msg', 'Unknown Error')}")
            return results
        results["actions"].append(f"Login Check Success (Code: {login.get('code')})")

        # 3. Daily Sign (1 & 2)
        for s_type in [1, 2]:
            res = self.sign_in(user_id, token, s_type)
            results["actions"].append(f"sign_type_{s_type} (Code: {res.get('code')}, Msg: {res.get('msg')})")
            time.sleep(0.5)

        # 4. Task Management
        tasks_response = self.get_task_list(user_id, token)
        if tasks_response.get("code") != 0:
             results["errors"].append(f"Get Task List Failed (Code {tasks_response.get('code')}): {tasks_response.get('msg')}")
             return results
             
        results["actions"].append(f"Task List Received (Code: {tasks_response.get('code')})")
        # Using 'task_config' as per your original JS analysis, though 'task_list_config' is also possible
        task_config = tasks_response.get("data", {}).get("task_config", []) 
        
        for task in task_config:
            if str(task.get("status")) == "1": 
                t_id = task.get("task_id") or task.get("id")
                if t_id:
                    apply_res = self.apply_task(user_id, token, t_id)
                    results["actions"].append(f"Task {t_id} Applied (Code: {apply_res.get('code')})")
                    time.sleep(0.2)

        # 5. Box Opening
        for b_id in [1, 2, 3]:
            box_res = self.open_box(user_id, token, b_id)
            results["actions"].append(f"Box {b_id} Opened (Code: {box_res.get('code')}, Msg: {box_res.get('msg')})")

        return results

# Example usage block remains the same for testing
if __name__=="__main__":
    session = requests.Session()
    h5_bot = DazzH5Client(session=session)
    
    user_id = "20516606" # Use the ID from your failing output
    token = "dad7bc938af6f369" # Use the token from your failing output
    
    print(f"Initializing session for user {user_id}...")
    h5_bot.init_signtask_page(user_id, token)
    
    print("Running daily workflow...")
    report = h5_bot.run_daily_workflow(user_id, token)
    
    print("\n--- Execution Report ---")
    for action in report["actions"]:
        print(action)
    
    if report["errors"]:
        print("\n--- Errors Encountered ---")
        for error in report["errors"]:
            print(error)
    else:
        print("\nWorkflow completed without recorded critical errors.")