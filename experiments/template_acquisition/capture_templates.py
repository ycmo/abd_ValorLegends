import argparse
import sys
import os
import time
import json
import cv2
import numpy as np
import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from adb_controller import DeviceController
from vision_matcher import VisionMatcher

NODE_TEMPLATES = {
    "main_campaign": [
        {"name": "home_anchor", "box": (0, 0, 200, 150), "intended_use": "anchor", "selector_type": "top_title"},
        {"name": "bottom_wild_tab", "box": (400, 780, 550, 900), "intended_use": "button", "selector_type": "bottom_nav"}
    ],
    "daily_tasks": [
        {"name": "daily_tasks_anchor", "box": (80, 20, 350, 100), "intended_use": "anchor", "selector_type": "top_title"},
        {"name": "daily_task_endless_trial_row", "box": (100, 360, 400, 460), "intended_use": "anchor", "selector_type": "task_list_area"},
        {"name": "daily_task_go_button", "box": (1300, 370, 1500, 460), "intended_use": "button", "selector_type": "dynamic_row_button"}
    ],
    "endless_trial": [
        {"name": "endless_trial_title", "box": (50, 20, 300, 100), "intended_use": "anchor", "selector_type": "top_title"},
        {"name": "sub_dungeon_option", "box": (600, 300, 1000, 700), "intended_use": "button", "selector_type": "center_map"}
    ]
}

class TemplateAcquisition:
    def __init__(self, serial, debug_mode):
        self.device = DeviceController(serial)
        self.debug_mode = debug_mode
        self.graph_path = os.path.join(PROJECT_ROOT, "data", "status_graph.json")
        self.acq_dir = os.path.join(PROJECT_ROOT, "screenshots", "acquisition")
        self.cand_dir = os.path.join(PROJECT_ROOT, "assets", "candidates")
        self.overlay_dir = os.path.join(PROJECT_ROOT, "screenshots", "debug_overlay")
        
        os.makedirs(self.acq_dir, exist_ok=True)
        os.makedirs(self.cand_dir, exist_ok=True)
        os.makedirs(self.overlay_dir, exist_ok=True)
        
        self.load_graph()
        self.matcher = VisionMatcher(debug=False)

    def load_graph(self):
        with open(self.graph_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.nodes = {n["node_id"]: n for n in data["nodes"]}
        self.edges = data["edges"]
        
        # Build adjacency list
        self.adj = {n: [] for n in self.nodes}
        for e in self.edges:
            if e["risk_level"] == "none":
                self.adj[e["from_node"]].append(e)

    def detect_current_node(self, screen):
        # We rely on templates defined in status_graph.json
        # Currently, daily_tasks has assets/daily_tasks_title.png
        # main_campaign has assets/task_button.png
        for node_id, node_data in self.nodes.items():
            for tmpl_path in node_data.get("templates", []):
                full_tmpl_path = os.path.join(PROJECT_ROOT, tmpl_path)
                passed, conf = self.matcher.check_anchor(screen, full_tmpl_path)
                if passed:
                    return node_id
        return None

    def find_path(self, start_node, target_node):
        queue = [[start_node]]
        visited = set([start_node])
        
        while queue:
            path = queue.pop(0)
            node = path[-1]
            if node == target_node:
                return path
            
            for edge in self.adj.get(node, []):
                if edge["to_node"] not in visited:
                    visited.add(edge["to_node"])
                    queue.append(path + [edge["to_node"]])
        return None

    def stop_for_human_review(self, reason):
        print(f"\n[STOPPED_FOR_HUMAN_REVIEW] {reason}")
        sys.exit(1)

    def navigate_to(self, target_node):
        if target_node not in NODE_TEMPLATES:
            self.stop_for_human_review(f"Target node {target_node} not in supported minimal scope.")
            
        screen = self.device.screenshot()
        curr_node = self.detect_current_node(screen)
        print(f"Detected current node: {curr_node}")
        
        if curr_node == target_node:
            print("Already at target node.")
            return True
            
        if not curr_node:
            self.stop_for_human_review("Cannot detect current node. Unknown state.")
            
        path = self.find_path(curr_node, target_node)
        if not path:
            self.stop_for_human_review(f"No safe path found from {curr_node} to {target_node}.")
            
        print(f"Found safe path: {' -> '.join(path)}")
        
        for i in range(len(path) - 1):
            u = path[i]
            v = path[i+1]
            # find edge
            edge = next(e for e in self.adj[u] if e["to_node"] == v)
            print(f"Executing edge {u} -> {v} via {edge['action_type']}")
            
            if edge["action_type"] == "tap" and edge["selector_type"] == "coordinate":
                x = edge["coordinate"]["x"]
                y = edge["coordinate"]["y"]
                self.device.tap(x, y)
            elif edge["action_type"] == "keyevent" and edge["selector_type"] == "fixed_sequence":
                # Assuming back for simple keyevents
                self.device.back()
            else:
                self.stop_for_human_review(f"Unknown action {edge['action_type']} {edge['selector_type']}")
                
            wait_sec = self.nodes[v].get("wait_seconds", 3.0)
            time.sleep(wait_sec)
            
        return True

    def capture_templates(self, node_id):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        screen = self.device.screenshot()
        
        full_path = os.path.join(self.acq_dir, f"{node_id}_{ts}_full.png")
        cv2.imwrite(full_path, screen)
        print(f"\nSaved full screenshot: {full_path}")
        
        overlay = screen.copy()
        
        reqs = NODE_TEMPLATES.get(node_id, [])
        for req in reqs:
            name = req["name"]
            x1, y1, x2, y2 = req["box"]
            
            # Crop
            crop = screen[y1:y2, x1:x2]
            cand_path = os.path.join(self.cand_dir, f"{node_id}_{name}_{ts}.png")
            cv2.imwrite(cand_path, crop)
            
            # Draw on overlay
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(overlay, name, (x1, max(0, y1-5)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
            
            # Write metadata
            meta = {
                "node_id": node_id,
                "screenshot_path": full_path,
                "candidate_template_path": cand_path,
                "suggested_final_path": f"assets/{req['intended_use']}s/{name}.png",
                "crop_box": [x1, y1, x2, y2],
                "intended_use": req["intended_use"],
                "selector_type": req["selector_type"],
                "source": "auto_candidate",
                "review_status": "pending",
                "notes": f"Auto captured from {node_id} at {ts}"
            }
            meta_path = os.path.join(self.cand_dir, f"{node_id}_{ts}_{name}_candidate.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
                
            print(f"Generated candidate: {cand_path}")
            
        overlay_path = os.path.join(self.overlay_dir, f"{node_id}_{ts}_overlay.png")
        cv2.imwrite(overlay_path, overlay)
        print(f"Saved debug overlay: {overlay_path}")

    def run(self, target_node):
        if not self.device.connect():
            self.stop_for_human_review("Failed to connect to device.")
            
        self.navigate_to(target_node)
        self.capture_templates(target_node)
        print("\nAcquisition completed successfully. Please review candidates.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", type=str, required=True, help="Target node to capture templates for")
    parser.add_argument("--serial", type=str, default="127.0.0.1:5555")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    app = TemplateAcquisition(args.serial, args.debug)
    app.run(args.node)
