# -*- coding: utf-8 -*-
import cv2
import threading
import time
import numpy as np
import random
from datetime import datetime
from flask import Flask, render_template, Response, redirect, url_for, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

app = Flask(__name__, template_folder='../frontend/templates', static_folder='../frontend/static')
app.secret_key = 'super_secret_cyber_key'  # Change this in production

# Initialize Groq API client (OpenAI-compatible)
client = OpenAI(
    api_key=os.getenv('GROQ_API_KEY'),
    base_url=os.getenv('OPENAI_BASE_URL')
)
LLM_MODEL = os.getenv('LLM_MODEL', 'llama-3.1-8b-instant')

# --- Conversation Memory System ---
conversation_sessions = {}

class ConversationManager:
    """Manages conversation history and context for multi-turn dialogues"""
    
    def __init__(self, session_id):
        self.session_id = session_id
        self.messages = []
        self.context = {
            'current_page': None,
            'last_camera_viewed': None,
            'tracked_employees': [],
            'preferences': {
                'response_style': 'professional',
                'auto_navigate': True
            }
        }
        self.created_at = datetime.now()
        self.last_interaction = datetime.now()
    
    def add_message(self, role, content):
        """Add a message to conversation history"""
        self.messages.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        })
        self.last_interaction = datetime.now()
        
        # Keep only last 10 messages to manage context window
        if len(self.messages) > 20:
            self.messages = self.messages[-20:]
    
    def get_conversation_history(self, max_messages=10):
        """Get recent conversation history for AI context"""
        return self.messages[-max_messages:]
    
    def update_context(self, key, value):
        """Update conversation context"""
        self.context[key] = value
    
    def get_context(self):
        """Get current conversation context"""
        return self.context
    
    def clear(self):
        """Clear conversation history"""
        self.messages = []
        self.context['tracked_employees'] = []

def get_conversation(session_id):
    """Get or create conversation session"""
    if session_id not in conversation_sessions:
        conversation_sessions[session_id] = ConversationManager(session_id)
    return conversation_sessions[session_id]

def get_system_context():
    """Provide real-time system context for AI"""
    # Camera status
    online_cameras = len([c for c in CAMERAS_CONFIG])
    total_cameras = len(CAMERAS_CONFIG)
    
    # Mock some offline cameras for demo
    offline_cameras = random.sample(CAMERAS_CONFIG, min(2, len(CAMERAS_CONFIG))) if random.random() > 0.7 else []
    offline_count = len(offline_cameras)
    online_count = total_cameras - offline_count
    
    # Recent activity
    current_time = datetime.now().strftime("%H:%M")
    
    context = {
        'system_status': {
            'cameras_online': online_count,
            'cameras_total': total_cameras,
            'offline_cameras': [c['name'] for c in offline_cameras] if offline_cameras else [],
            'current_time': current_time
        },
        'employees': {
            'total': len(tracker.mock_employees),
            'names': tracker.mock_employees
        },
        'cameras': {
            'working_areas': [c for c in CAMERAS_CONFIG if c['category'] == 'working'],
            'restricted_areas': [c for c in CAMERAS_CONFIG if c['category'] == 'non-working']
        }
    }
    
    return context

# --- Authentication Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Mock User Database
class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

# Simple in-memory user store
users = {
    'admin': User('1', 'admin', 'admin123'),
    'monitor': User('2', 'monitor', 'securepass')
}

@login_manager.user_loader
def load_user(user_id):
    for user in users.values():
        if user.id == user_id:
            return user
    return None

# --- Configuration ---
# 16 Working Areas + 2 Non-Working Areas
CAMERAS_CONFIG = []

# Generate 16 Working Area Cameras
for i in range(1, 17):
    CAMERAS_CONFIG.append({
        'id': f'work_area_{i}',
        'name': f'Working Area {i}',
        'url': f'rtsp://user:pass@192.168.1.{100+i}/stream',
        'category': 'working'
    })

# Add 2 Non-Working Area Cameras
CAMERAS_CONFIG.append({
    'id': 'non_work_1', 
    'name': 'Non-Working Area 1', 
    'url': 'rtsp://user:pass@192.168.1.201/stream',
    'category': 'non-working'
})
CAMERAS_CONFIG.append({
    'id': 'non_work_2', 
    'name': 'Non-Working Area 2', 
    'url': 'rtsp://user:pass@192.168.1.202/stream',
    'category': 'non-working'
})


class VideoCamera(object):
    def __init__(self, source):
        self.source = source
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        
        # Start the background thread for execution
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()

    def create_test_frame(self, cam_name="Unknown"):
        """Generates a synthetic frame with timestamp"""
        # Cyber-theme colors (Neon Green/Blue)
        img = np.zeros((480, 640, 3), np.uint8)
        
        # Grid Background
        cv2.line(img, (0, 240), (640, 240), (50, 50, 50), 1)
        cv2.line(img, (320, 0), (320, 480), (50, 50, 50), 1)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(img, f"CAM: {cam_name}", (30, 50), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)  # Yellow/Cyan
        
        # Blinking Rec dot
        if int(time.time()) % 2 == 0:
            cv2.circle(img, (600, 40), 10, (0, 0, 255), -1)
            cv2.putText(img, "REC", (530, 45), cv2.FONT_HERSHEY_PLAIN, 1, (0, 0, 255), 1)

        cv2.putText(img, timestamp, (30, 450), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        
        # Simulation of movement
        seed = sum(ord(c) for c in str(self.source))
        t = time.time()
        x = int(320 + 200 * np.sin(t + seed))
        y = int(240 + 100 * np.cos(t + seed))
        
        # MOCK CV: Draw Bounding Box around "target"
        # Only draw if "person" is "detected" (simulated by simple logic)
        if int(t) % 5 != 0: # frequent detection
            # Draw brackets corners
            color = (0, 255, 0) # Green for working
            label = "PERSON: 98%"
            
            if "non_work" in self.source:
                color = (0, 0, 255) # Red for restricted
                label = "UNAUTHORIZED: 99%"

            cv2.rectangle(img, (x-30, y-30), (x+30, y+30), color, 2)
            cv2.putText(img, label, (x-40, y-40), cv2.FONT_HERSHEY_PLAIN, 1, color, 1)
            
            # Crosshair
            cv2.line(img, (x-10, y), (x+10, y), color, 1)
            cv2.line(img, (x, y-10), (x, y+10), color, 1)

        # Draw the object (simulated person)
        cv2.circle(img, (x, y), 15, (200, 200, 200), -1)
        
        return img

    def update(self):
        while self.running:
            # For this demo, we force the test frame to ensure UI looks good immediately
            # In production, uncomment the capture logic below
            """
            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
               # ... failover logic
            """
            
            # SIMULATED FEED
            with self.lock:
                self.frame = self.create_test_frame(str(self.source))
            time.sleep(0.05) # ~20 FPS simulation

    def get_frame(self):
        with self.lock:
            if self.frame is None:
                return None
            ret, jpeg = cv2.imencode('.jpg', self.frame)
            if ret:
                return jpeg.tobytes()
            return None

    def __del__(self):
        self.running = False

# Initialize all cameras
cameras = {}
for cam_conf in CAMERAS_CONFIG:
    cameras[cam_conf['id']] = VideoCamera(cam_conf['id']) # Pass ID as source for seeding

# --- Employee Tracking Mock Logic ---
class EmployeeTracker:
    def __init__(self):
        self.mock_employees = [
            "Mindii Chenaya", "Jane Smith", "Mike Ross", "Harvey Specter", "Louis Litt"
        ]
    
    def find_employee(self, name):
        # Mock logic: Randomly find the employee in one of the cameras or not found
        if not name:
            return {"status": "error", "message": "Name empty"}
        
        # Case insensitive search
        found = False
        real_name = ""
        for emp in self.mock_employees:
            if name.lower() in emp.lower():
                found = True
                real_name = emp
                break
        
        if not found:
             return {"found": False, "message": "Employee not found in database."}

        # Simulate detection
        is_visible = random.choice([True, True, False]) # 66% chance to be seen
        if is_visible:
            cam = random.choice(CAMERAS_CONFIG)
            return {
                "found": True,
                "name": real_name,
                "camera_id": cam['id'],
                "camera_name": cam['name'],
                "status": "Active",
                "last_seen": datetime.now().strftime("%H:%M:%S")
            }
        else:
            return {
                "found": False, 
                "name": real_name,
                "message": "Employee currently not visible in any feed."
            }

tracker = EmployeeTracker()


# --- Routes ---

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = users.get(username)
        if user and user.password == password:
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid Access Credentials")
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/monitor')
@login_required
def monitor():
    return render_template('monitor.html', cameras=CAMERAS_CONFIG)

@app.route('/track')
@login_required
def track_page():
    return render_template('tracking.html')

@app.route('/api/track_employee')
@login_required
def track_employee_api():
    name = request.args.get('name')
    result = tracker.find_employee(name)
    return jsonify(result)

# --- New Features Routes ---

@app.route('/analytics')
@login_required
def analytics():
    return render_template('analytics.html')

@app.route('/api/analytics_data')
@login_required
def analytics_data():
    # Mock Data for charts
    data = {
        "detections_per_hour": [12, 19, 3, 5, 2, 3, 45], # 7 time points
        "zone_activity": [65, 59, 90, 81, 56, 55], # 6 zones
        "employee_distribution": [300, 50, 100], # Active, Idle, Away
    }
    return jsonify(data)

@app.route('/map')
@login_required
def map_page():
    return render_template('map.html', cameras=CAMERAS_CONFIG)

@app.route('/api/map_data')
@login_required
def map_data():
    # Return simulated locations of employees on the map
    # A list of dots with x, y coordinates
    dots = []
    for _ in range(5):
        dots.append({
            "x": random.randint(10, 90), # % positions
            "y": random.randint(10, 90),
            "name": random.choice(["John", "Jane", "Mike"])
        })
    return jsonify(dots)

@app.route('/api/call_agent', methods=['POST'])
@login_required
def call_agent():
    """
    Enhanced Call Agent API - AI-powered responses with conversation memory
    """
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        session_id = data.get('session_id', current_user.id)
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
        
        # Get conversation session
        conversation = get_conversation(session_id)
        conversation.add_message('user', user_message)
        
        # Get system context
        sys_context = get_system_context()
        
        # Analyze intent and determine actions
        actions = parse_intent(user_message, conversation)
        
        # Build enhanced system prompt with real-time data
        system_prompt = f"""You are OREL, a friendly and intelligent AI assistant for the OREL EYE surveillance system! 🤖✨

YOUR PERSONALITY:
- Friendly, enthusiastic, and helpful - like a knowledgeable colleague who loves their job!
- Use emojis to add warmth and visual appeal (🎥📊🔍⚡👋🌟💡🎯)
- Conversational and casual, but professional when discussing security
- Proactive - suggest helpful actions and insights
- Empathetic - understand the user's needs and respond accordingly
- Show excitement when sharing good news, concern when appropriate

CURRENT SYSTEM STATUS:
🎥 Cameras: {sys_context['system_status']['cameras_online']}/{sys_context['system_status']['cameras_total']} online {"✅" if sys_context['system_status']['cameras_online'] == sys_context['system_status']['cameras_total'] else "⚠️"}
⏰ Time: {sys_context['system_status']['current_time']}
👥 Employees tracked: {', '.join(sys_context['employees']['names'][:3])}{"..." if len(sys_context['employees']['names']) > 3 else ""}
📍 Working areas: {len(sys_context['cameras']['working_areas'])} cameras
🚫 Restricted zones: {len(sys_context['cameras']['restricted_areas'])} cameras
{f"⚠️ Heads up! Offline: {', '.join(sys_context['system_status']['offline_cameras'])}" if sys_context['system_status']['offline_cameras'] else ""}

WHAT YOU CAN DO:
✅ Monitor all camera feeds in real-time
✅ Track employees and show their locations
✅ Analyze security data and spot patterns
✅ Navigate to different system pages instantly
✅ Provide security insights and recommendations
✅ Alert you to important events

CONVERSATION STYLE:
- Start responses with enthusiasm ("Great question!", "Absolutely!", "Sure thing!", "You got it!")
- Verify actions clearly ("I'll check the cameras...", "Navigating to tracking...", "Scanning for Mike...")
- Use bold text for key information (**3 anomalies detected**)
- Keep it punchy and easy to read

Available pages:
- /dashboard - Main Command Center
- /monitor - Live Camera Grid
- /track - Employee Tracker
- /map - Facility Floor Plan
- /analytics - Analytics Dashboard
- /database - Face Database
- /reports - Reporting Center
- /settings - System Configuration

Respond to the user naturally based on their request and the provided context. If they ask to perform an action, confirm you are doing it.
"""
             
        try:
            # Call Groq API (via OpenAI-compatible client)
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend([
                {"role": m['role'], "content": m['content']} 
                for m in conversation.get_conversation_history()
            ])
            
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=250
            )
            
            ai_response = response.choices[0].message.content
        except Exception as api_error:
            # Fallback to keyword response if API fails
            ai_response = generate_keyword_response(user_message, actions)
        
        # Add AI response to history
        conversation.add_message('assistant', ai_response)
        
        return jsonify({
            'success': True,
            'response': ai_response,
            'actions': actions
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# --- Expansion Routes ---

@app.route('/database')
@login_required
def database():
    return render_template('database.html')

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

@app.route('/api/system_health')
@login_required
def system_health():
    """API for System Health Widget"""
    # Mock health data
    return jsonify({
        "server_status": "Online",
        "latency_ms": random.randint(15, 45),
        "storage_usage_percent": 75,
        "cpu_load_percent": random.randint(20, 40),
        "ai_status": "Active"
    })

@app.route('/api/quick_stats')
@login_required
def quick_stats():
    """API for Quick Attendance & Dashboard Stats"""
    return jsonify({
        "present_count": 42,
        "total_employees": 50,
        "unknown_faces": 2,
        "active_alerts": 3
    })

def generate_keyword_response(message, actions, sys_context=None):
    """Generate friendly response based on keywords without AI"""
    msg_lower = message.lower()
    
    # Greeting responses
    if any(word in msg_lower for word in ['hello', 'hi', 'hey', 'greetings']):
        return "Hey there! 👋 I'm OREL, your AI surveillance buddy! Ready to help you monitor cameras, track employees, or dive into analytics. What can I do for you?"
    
    # Navigation responses
    if any(word in msg_lower for word in ['dashboard', 'home', 'main']):
        return "You got it! 🏠 Taking you to the main dashboard now - your command center awaits!"
    elif any(word in msg_lower for word in ['monitor', 'camera', 'surveillance', 'feed']):
        return "Absolutely! 🎥 Opening the camera grid for you - let's see what's happening across all zones!"
    elif any(word in msg_lower for word in ['track', 'find', 'locate']):
        if actions and any(a['type'] == 'search_employee' for a in actions):
            name = next((a['name'] for a in actions if a['type'] == 'search_employee'), 'employee')
            return f"Perfect! 🔍 Searching for {name} across all camera feeds now... I'll show you their location in just a moment!"
        return "Sure thing! 🎯 Opening the employee tracking system - tell me who you're looking for!"
    elif any(word in msg_lower for word in ['map', 'floor', 'layout', 'facility']):
        return "Great choice! 🗺️ Pulling up the interactive facility map - you'll see live employee positions in seconds!"
    elif any(word in msg_lower for word in ['analytics', 'data', 'stats', 'report']):
        return "Excellent! 📊 Loading the analytics dashboard with all the juicy insights and trends!"
    elif any(word in msg_lower for word in ['alert', 'breach', 'emergency']):
        return "⚠️ Security alert activated! The team will be notified immediately!"
    
    # General help
    elif any(word in msg_lower for word in ['help', 'what can', 'how do', 'capabilities']):
        return ("Happy to help! Here's what I can do:\n\n"
                "- Monitor all cameras\n"
                "- Track employees in real-time\n"  
                "- Show analytics & insights\n"
                "- Display facility map\n"
                "- Navigate anywhere instantly\n\n"
                'Just ask naturally - I\'ll understand! Try "show me the cameras" or "where is Mike?"')
    
    # Status queries with system context
    elif any(word in msg_lower for word in ['status', 'how many', 'count', 'online']):
        if sys_context:
            online = sys_context['system_status']['cameras_online']
            total = sys_context['system_status']['cameras_total']
            emp_count = sys_context['employees']['total']
            status_msg = "All good!" if online == total else "Some offline"
            overall_status = "running smoothly!" if online == total else "mostly operational"
            return (f"System Status Update:\n\n"
                   f"Cameras: {online}/{total} online ({status_msg})\n"
                   f"Tracking: {emp_count} employees\n"
                   f"Current time: {sys_context['system_status']['current_time']}\n\n"
                   f"Everything's {overall_status}")
        return "System Status: 18 cameras running smoothly, monitoring 5 employees across all zones! All systems go!"
    
    # Thank you
    elif any(word in msg_lower for word in ['thank', 'thanks', 'appreciate']):
        return "You're very welcome! Always happy to help! Need anything else? I'm here 24/7!"
    
    # Default response
    else:
        return ("I'm here to help! You can ask me to:\n\n"
                '- "Show cameras" or "Monitor feeds"\n'
                '- "Find [employee name]" or "Track someone"\n'  
                '- "Open analytics" or "Show stats"\n'
                '- "Display map" or "Floor plan"\n\n'
                "Just ask naturally - I understand!")


def parse_intent(message, conversation=None, sys_context=None):
    """Parse user message and extract actionable intents with context awareness"""
    actions = []
    msg_lower = message.lower()
    
    # Navigation intents
    if any(word in msg_lower for word in ['dashboard', 'home', 'main']):
        actions.append({'type': 'navigate', 'target': '/dashboard'})
    elif any(word in msg_lower for word in ['monitor', 'camera', 'surveillance', 'feed', 'show camera']):
        actions.append({'type': 'navigate', 'target': '/monitor'})
    elif any(word in msg_lower for word in ['track', 'find', 'locate', 'search employee']) and not any(word in msg_lower for word in ['where', 'who']):
        actions.append({'type': 'navigate', 'target': '/track'})
    elif any(word in msg_lower for word in ['map', 'floor', 'layout', 'facility']):
        actions.append({'type': 'navigate', 'target': '/map'})
    elif any(word in msg_lower for word in ['analytics', 'data', 'stats', 'report', 'chart']):
        actions.append({'type': 'navigate', 'target': '/analytics'})
    
    # Employee search intent with better name extraction
    if any(word in msg_lower for word in ['track', 'find', 'locate', 'where']) and any(word in msg_lower for word in ['employee', 'person', 'staff'] + (sys_context['employees']['names'] if sys_context else [])):
        # Try to extract employee name from system context
        if sys_context:
            for emp_name in sys_context['employees']['names']:
                if emp_name.lower() in msg_lower:
                    actions.append({
                        'type': 'search_employee', 
                        'name': emp_name
                    })
                    break
        else:
            # Fallback to common names
            common_names = ['mindii', 'jane', 'mike', 'harvey', 'louis']
            for name in common_names:
                if name in msg_lower:
                    actions.append({
                        'type': 'search_employee', 
                        'name': name.title() + ' ' + ('Chenaya' if name == 'mindii' else 
                                                       'Smith' if name == 'jane' else
                                                       'Ross' if name == 'mike' else
                                                       'Specter' if name == 'harvey' else 'Litt')
                    })
                    break
    
    # Camera-specific queries
    if any(word in msg_lower for word in ['camera', 'area', 'zone']):
        # Extract area number
        import re
        area_match = re.search(r'(?:area|camera|zone)\s*(\d+)', msg_lower)
        if area_match:
            area_num = area_match.group(1)
            actions.append({
                'type': 'show_camera',
                'camera_id': f'work_area_{area_num}',
                'area_number': area_num
            })
    
    # Alert intent
    if any(word in msg_lower for word in ['alert', 'breach', 'emergency', 'security']):
        if 'trigger' in msg_lower or 'activate' in msg_lower or 'test' in msg_lower:
            actions.append({'type': 'trigger_alert'})
    
    return actions

def generate_suggestions(message, actions, sys_context):
    """Generate contextual quick action suggestions"""
    suggestions = []
    msg_lower = message.lower()
    
    # Context-aware suggestions
    if 'camera' in msg_lower or 'monitor' in msg_lower:
        suggestions.extend([
            {'text': '📊 View Analytics', 'action': '/analytics'},
            {'text': '🗺️ Show Floor Map', 'action': '/map'}
        ])
    elif 'employee' in msg_lower or 'track' in msg_lower:
        suggestions.extend([
            {'text': '🎥 View All Cameras', 'action': '/monitor'},
            {'text': '🗺️ Show Location Map', 'action': '/map'}
        ])
    elif 'analytics' in msg_lower or 'data' in msg_lower:
        suggestions.extend([
            {'text': '🎥 View Cameras', 'action': '/monitor'},
            {'text': '🏠 Dashboard', 'action': '/dashboard'}
        ])
    else:
        # Default suggestions
        suggestions.extend([
            {'text': '🎥 Monitor Cameras', 'action': '/monitor'},
            {'text': '🔍 Track Employee', 'action': '/track'},
            {'text': '📊 Analytics', 'action': '/analytics'}
        ])
    
    return suggestions[:3]  # Limit to 3 suggestions



@app.route('/api/conversation_history', methods=['GET'])
@login_required
def get_conversation_history():
    """Get conversation history for current user"""
    session_id = request.args.get('session_id', current_user.id)
    conversation = get_conversation(session_id)
    
    return jsonify({
        'success': True,
        'messages': conversation.get_conversation_history(20),
        'context': conversation.get_context()
    })

@app.route('/api/clear_conversation', methods=['POST'])
@login_required
def clear_conversation():
    """Clear conversation history"""
    session_id = request.args.get('session_id', current_user.id)
    if session_id in conversation_sessions:
        conversation_sessions[session_id].clear()
    
    return jsonify({
        'success': True,
        'message': 'Conversation cleared'
    })

@app.route('/api/chatbot_status', methods=['GET'])
@login_required
def chatbot_status():
    """Get chatbot and system status"""
    sys_context = get_system_context()
    
    return jsonify({
        'success': True,
        'status': 'online',
        'model': LLM_MODEL,
        'system_context': sys_context
    })


def gen(camera_id):
    cam = cameras.get(camera_id)
    if not cam:
        return ""
        
    while True:
        frame = cam.get_frame()
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
        else:
            time.sleep(0.1)

@app.route('/video_feed/<camera_id>')
@login_required
def video_feed(camera_id):
    # Determine if we want to protect video feeds too. Usually yes.
    return Response(gen(camera_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/analytics_detailed')
@login_required
def analytics_detailed():
    """Serve detailed mock data for the advanced analytics dashboard"""
    return jsonify({
        # KPI Data
        'kpi': {
            'occupancy': {'current': 142, 'capacity': 200},
            'attendance': 94,  # Percentage
            'productivity': 87, # Percentage
            'alerts_today': 3
        },
        # Productivity Trend (Time vs Level)
        'productivity_trend': {
            'labels': ['08:00', '09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00'],
            'values': [45, 78, 85, 92, 60, 88, 91, 85]
        },
        # Department Comparison
        'dept_comparison': {
            'labels': ['IT Dev', 'Sales', 'HR', 'Ops'],
            'active_time_avg': [7.2, 6.5, 6.8, 7.5] # Hours
        },
        # Active vs Idle Split
        'work_split': [65, 20, 15], # Active, Idle, Break
        
        # Real-time Alerts Log
        'recent_alerts': [
            {'time': '14:32', 'event': 'Restricted Access: Server Room', 'level': 'high'},
            {'time': '13:15', 'event': 'Unknown Person: Lobby', 'level': 'medium'},
            {'time': '11:45', 'event': 'Door Forced: Rear Exit', 'level': 'critical'},
            {'time': '09:10', 'event': 'Camera Offline: Zone B', 'level': 'low'},
            {'time': '08:55', 'event': 'Late Entry: J. Specter', 'level': 'low'}
        ]
    })

if __name__ == '__main__':
    try:
        from waitress import serve
        print("Starting OREL EYE Production Server...")
        print("Optimized for Windows - Multi-threaded Load Balancing Active")
        print("Serving on http://127.0.0.1:5000")
        
        # Production configuration with Waitress
        serve(app, host='0.0.0.0', port=5000, threads=16, connection_limit=1000, channel_timeout=30)
        
    except ImportError:
        # Fallback to dev server if waitress is not installed
        print("Waitress not found. Falling back to Flask development server.")
        print("Run 'pip install waitress' for production performance.")
        app.run(host='0.0.0.0', port=5000, debug=True)
