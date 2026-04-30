from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
from sqlalchemy import or_
from zoneinfo import ZoneInfo
import re
import os

app = Flask(__name__, static_folder='frontend', static_url_path='')
CORS(app, origins="*")

# Database: Use PostgreSQL in production (Railway), SQLite in dev
database_url = os.environ.get('DATABASE_URL', 'sqlite:///taskmanager.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'change-this-in-production-super-secret')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=7)

db = SQLAlchemy(app)
jwt = JWTManager(app)
IST = ZoneInfo('Asia/Kolkata')

# ─── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'email': self.email, 'created_at': self.created_at.isoformat()}

class ProjectMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(20), default='member')
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, default='')
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    members = db.relationship('ProjectMember', backref='project', cascade='all, delete-orphan')
    tasks = db.relationship('Task', backref='project', cascade='all, delete-orphan')

    def to_dict(self, user_id=None):
        owner = User.query.get(self.owner_id)
        members = []
        for m in self.members:
            u = User.query.get(m.user_id)
            if u:
                members.append({'id': u.id, 'name': u.name, 'email': u.email, 'role': m.role})
        my_role = None
        if user_id:
            m = ProjectMember.query.filter_by(project_id=self.id, user_id=user_id).first()
            my_role = m.role if m else None
        return {
            'id': self.id, 'name': self.name, 'description': self.description,
            'owner_id': self.owner_id,
            'owner': owner.to_dict() if owner else None,
            'members': members,
            'my_role': my_role,
            'task_count': len(self.tasks),
            'created_at': self.created_at.isoformat()
        }

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    status = db.Column(db.String(30), default='todo')
    priority = db.Column(db.String(20), default='medium')
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    due_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        assignee = User.query.get(self.assignee_id) if self.assignee_id else None
        creator = User.query.get(self.created_by)
        is_overdue = is_task_overdue(self)
        return {
            'id': self.id, 'title': self.title, 'description': self.description,
            'status': self.status, 'priority': self.priority,
            'project_id': self.project_id,
            'assignee': assignee.to_dict() if assignee else None,
            'assignee_id': self.assignee_id,
            'created_by': creator.to_dict() if creator else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'is_overdue': is_overdue,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class TaskComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        author = User.query.get(self.user_id)
        return {
            'id': self.id,
            'task_id': self.task_id,
            'project_id': self.project_id,
            'user_id': self.user_id,
            'author': author.to_dict() if author else None,
            'content': self.content,
            'created_at': self.created_at.isoformat()
        }

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('task_comment.id'), nullable=True)
    kind = db.Column(db.String(30), nullable=False, default='mention')
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'project_id': self.project_id,
            'task_id': self.task_id,
            'comment_id': self.comment_id,
            'kind': self.kind,
            'message': self.message,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat()
        }

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(60), nullable=False)
    details = db.Column(db.String(255), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        actor = User.query.get(self.actor_id)
        target_user = User.query.get(self.target_user_id) if self.target_user_id else None
        task = Task.query.get(self.task_id) if self.task_id else None
        return {
            'id': self.id,
            'project_id': self.project_id,
            'actor': actor.to_dict() if actor else None,
            'action': self.action,
            'details': self.details,
            'task_id': self.task_id,
            'task_title': task.title if task else None,
            'target_user': target_user.to_dict() if target_user else None,
            'created_at': self.created_at.isoformat()
        }

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_project_role(project_id, user_id):
    m = ProjectMember.query.filter_by(project_id=project_id, user_id=user_id).first()
    return m.role if m else None

def require_project_access(project_id, user_id, min_role=None):
    project = Project.query.get(project_id)
    if not project:
        return None, jsonify({'error': 'Project not found'}), 404
    role = get_project_role(project_id, user_id)
    if not role:
        return None, jsonify({'error': 'Access denied'}), 403
    if min_role == 'admin' and role != 'admin':
        return None, jsonify({'error': 'Admin access required'}), 403
    return project, None, None

def extract_mentioned_user_ids(project_id, comment_text):
    members = ProjectMember.query.filter_by(project_id=project_id).all()
    if not members:
        return []

    mentioned_ids = set()
    member_user_ids = [m.user_id for m in members]
    users = User.query.filter(User.id.in_(member_user_ids)).all() if member_user_ids else []
    by_email = {u.email.lower(): u.id for u in users}
    by_name_token = {}
    for u in users:
        first = (u.name or '').strip().split(' ')[0].lower()
        if first:
            by_name_token[first] = u.id

    for email in re.findall(r'@([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', comment_text or ''):
        uid = by_email.get(email.lower())
        if uid:
            mentioned_ids.add(uid)

    for token in re.findall(r'@([A-Za-z0-9_.-]{2,})', comment_text or ''):
        uid = by_name_token.get(token.lower())
        if uid:
            mentioned_ids.add(uid)

    return list(mentioned_ids)

def push_notification(user_id, project_id, message, kind='system', task_id=None, comment_id=None):
    db.session.add(Notification(
        user_id=user_id,
        project_id=project_id,
        task_id=task_id,
        comment_id=comment_id,
        kind=kind,
        message=message
    ))

def get_admin_user_ids(project_id):
    admins = ProjectMember.query.filter_by(project_id=project_id, role='admin').all()
    return [m.user_id for m in admins]

def log_activity(project_id, actor_id, action, details, task_id=None, target_user_id=None):
    db.session.add(ActivityLog(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        details=details,
        task_id=task_id,
        target_user_id=target_user_id
    ))

def _normalize_due_date(due_date):
    if not due_date:
        return None
    return due_date if due_date.tzinfo else due_date.replace(tzinfo=timezone.utc)

def is_task_overdue(task):
    if not task.due_date or task.status == 'done':
        return False
    now_utc = datetime.now(timezone.utc)
    if task.due_date.tzinfo:
        due_utc = task.due_date.astimezone(timezone.utc)
    else:
        # Treat timezone-less values as IST wall-clock time.
        due_utc = task.due_date.replace(tzinfo=IST).astimezone(timezone.utc)
    return due_utc < now_utc

def is_due_within_next_24h(task):
    if not task.due_date or task.status == 'done':
        return False
    now_utc = datetime.now(timezone.utc)
    if task.due_date.tzinfo:
        due_utc = task.due_date.astimezone(timezone.utc)
    else:
        due_utc = task.due_date.replace(tzinfo=IST).astimezone(timezone.utc)
    return now_utc <= due_utc <= (now_utc + timedelta(hours=24))

def _has_recent_due_soon_notification(user_id, task_id):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    recent = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.task_id == task_id,
        Notification.kind == 'due_soon',
        Notification.created_at >= cutoff
    ).first()
    return recent is not None

def notify_due_soon_for_task(task):
    if not is_due_within_next_24h(task):
        return

    recipient_ids = set()
    if task.assignee_id:
        recipient_ids.add(task.assignee_id)

    due_label = task.due_date.strftime('%Y-%m-%d %H:%M')
    for uid in recipient_ids:
        if _has_recent_due_soon_notification(uid, task.id):
            continue
        push_notification(
            user_id=uid,
            project_id=task.project_id,
            task_id=task.id,
            kind='due_soon',
            message=f"Task '{task.title}' is due within 24h ({due_label})"
        )

def generate_due_soon_notifications_for_user(user_id):
    memberships = ProjectMember.query.filter_by(user_id=user_id).all()
    if not memberships:
        return
    project_ids = [m.project_id for m in memberships]
    tasks = Task.query.filter(
        Task.project_id.in_(project_ids),
        Task.due_date.isnot(None),
        Task.status != 'done'
    ).all()

    for task in tasks:
        if not is_due_within_next_24h(task):
            continue
        is_assignee = task.assignee_id == user_id
        if not is_assignee:
            continue
        if _has_recent_due_soon_notification(user_id, task.id):
            continue
        due_label = task.due_date.strftime('%Y-%m-%d %H:%M')
        push_notification(
            user_id=user_id,
            project_id=task.project_id,
            task_id=task.id,
            kind='due_soon',
            message=f"Task '{task.title}' is due within 24h ({due_label})"
        )

# ─── Frontend Serving ─────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('frontend', 'index.html')

@app.errorhandler(404)
def not_found(err):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    return err

@app.errorhandler(Exception)
def handle_unexpected_error(err):
    if request.path.startswith('/api/'):
        app.logger.exception('Unhandled API error: %s', err)
        return jsonify({'error': 'Internal server error'}), 500
    raise err

# ─── Auth Routes ──────────────────────────────────────────────────────────────

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not name or not email or not password:
        return jsonify({'error': 'Name, email, and password are required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409
    user = User(name=name, email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    token = create_access_token(identity=str(user.id))
    return jsonify({'token': token, 'user': user.to_dict()}), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password'}), 401
    token = create_access_token(identity=str(user.id))
    return jsonify({'token': token, 'user': user.to_dict()})

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    return jsonify(user.to_dict())

# ─── User Routes ──────────────────────────────────────────────────────────────

@app.route('/api/users/search', methods=['GET'])
@jwt_required()
def search_users():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    users = User.query.filter(
        (User.name.ilike(f'%{q}%')) | (User.email.ilike(f'%{q}%'))
    ).limit(10).all()
    return jsonify([u.to_dict() for u in users])

# ─── Project Routes ───────────────────────────────────────────────────────────

@app.route('/api/projects', methods=['GET'])
@jwt_required()
def get_projects():
    user_id = int(get_jwt_identity())
    memberships = ProjectMember.query.filter_by(user_id=user_id).all()
    project_ids = [m.project_id for m in memberships]
    projects = Project.query.filter(Project.id.in_(project_ids)).order_by(Project.created_at.desc()).all()
    return jsonify([p.to_dict(user_id) for p in projects])

@app.route('/api/projects', methods=['POST'])
@jwt_required()
def create_project():
    user_id = int(get_jwt_identity())
    data = request.get_json()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Project name is required'}), 400
    project = Project(name=name, description=data.get('description', ''), owner_id=user_id)
    db.session.add(project)
    db.session.flush()
    db.session.add(ProjectMember(project_id=project.id, user_id=user_id, role='admin'))
    log_activity(project.id, user_id, 'project_created', f"Created project '{project.name}'")
    db.session.commit()
    return jsonify(project.to_dict(user_id)), 201

@app.route('/api/projects/<int:project_id>', methods=['GET'])
@jwt_required()
def get_project(project_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id)
    if err: return err, code
    return jsonify(project.to_dict(user_id))

@app.route('/api/projects/<int:project_id>', methods=['PUT'])
@jwt_required()
def update_project(project_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id, min_role='admin')
    if err: return err, code
    data = request.get_json()
    if 'name' in data and data['name'].strip():
        project.name = data['name'].strip()
    if 'description' in data:
        project.description = data['description']
    db.session.commit()
    return jsonify(project.to_dict(user_id))

@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
@jwt_required()
def delete_project(project_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id, min_role='admin')
    if err: return err, code
    if project.owner_id != user_id:
        return jsonify({'error': 'Only the owner can delete a project'}), 403
    db.session.delete(project)
    db.session.commit()
    return jsonify({'message': 'Project deleted'})

@app.route('/api/projects/<int:project_id>/members', methods=['POST'])
@jwt_required()
def add_member(project_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id, min_role='admin')
    if err: return err, code
    data = request.get_json()
    target_id = data.get('user_id')
    role = data.get('role', 'member')
    if role not in ('admin', 'member'):
        return jsonify({'error': 'Role must be admin or member'}), 400
    target = User.query.get(target_id)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    existing = ProjectMember.query.filter_by(project_id=project_id, user_id=target_id).first()
    actor = User.query.get(user_id)
    actor_name = actor.name if actor else 'An admin'
    if existing:
        role_changed = existing.role != role
        existing.role = role
        if role_changed and target_id != user_id:
            push_notification(
                user_id=target_id,
                project_id=project_id,
                task_id=None,
                kind='role_update',
                message=f"{actor_name} changed your role to {role} in project: {project.name}"
            )
    else:
        db.session.add(ProjectMember(project_id=project_id, user_id=target_id, role=role))
        if target_id != user_id:
            push_notification(
                user_id=target_id,
                project_id=project_id,
                task_id=None,
                kind='member_added',
                message=f"{actor_name} added you to project: {project.name} as {role}"
            )
        log_activity(project_id, user_id, 'member_added', f"Added {target.name} as {role}", target_user_id=target_id)
    if existing and role_changed:
        log_activity(project_id, user_id, 'member_role_changed', f"Changed {target.name} role to {role}", target_user_id=target_id)
    db.session.commit()
    return jsonify(project.to_dict(user_id))

@app.route('/api/projects/<int:project_id>/members/<int:target_user_id>', methods=['DELETE'])
@jwt_required()
def remove_member(project_id, target_user_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id, min_role='admin')
    if err: return err, code
    if target_user_id == project.owner_id:
        return jsonify({'error': 'Cannot remove project owner'}), 400
    member = ProjectMember.query.filter_by(project_id=project_id, user_id=target_user_id).first()
    if member:
        target = User.query.get(target_user_id)
        target_name = target.name if target else f'User {target_user_id}'
        log_activity(project_id, user_id, 'member_removed', f"Removed {target_name} from project", target_user_id=target_user_id)
        db.session.delete(member)
        db.session.commit()
    return jsonify({'message': 'Member removed'})

@app.route('/api/projects/<int:project_id>/members/<int:target_user_id>/role', methods=['PUT'])
@jwt_required()
def update_member_role(project_id, target_user_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id, min_role='admin')
    if err: return err, code
    data = request.get_json()
    role = data.get('role')
    if role not in ('admin', 'member'):
        return jsonify({'error': 'Role must be admin or member'}), 400
    member = ProjectMember.query.filter_by(project_id=project_id, user_id=target_user_id).first()
    if not member:
        return jsonify({'error': 'Member not found'}), 404
    old_role = member.role
    member.role = role
    if target_user_id != user_id and old_role != role:
        actor = User.query.get(user_id)
        actor_name = actor.name if actor else 'An admin'
        push_notification(
            user_id=target_user_id,
            project_id=project_id,
            task_id=None,
            kind='role_update',
            message=f"{actor_name} changed your role to {role} in project: {project.name}"
        )
    if old_role != role:
        target = User.query.get(target_user_id)
        target_name = target.name if target else f'User {target_user_id}'
        log_activity(project_id, user_id, 'member_role_changed', f"Changed {target_name} role from {old_role} to {role}", target_user_id=target_user_id)
    db.session.commit()
    return jsonify(project.to_dict(user_id))

# ─── Task Routes ──────────────────────────────────────────────────────────────

@app.route('/api/projects/<int:project_id>/tasks', methods=['GET'])
@jwt_required()
def get_tasks(project_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id)
    if err: return err, code
    tasks = Task.query.filter_by(project_id=project_id).order_by(Task.created_at.desc()).all()
    return jsonify([t.to_dict() for t in tasks])

@app.route('/api/projects/<int:project_id>/tasks', methods=['POST'])
@jwt_required()
def create_task(project_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id)
    if err: return err, code
    role = get_project_role(project_id, user_id)
    if role != 'admin':
        return jsonify({'error': 'Only admins can create tasks'}), 403

    data = request.get_json()
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Task title is required'}), 400
    due_date = None
    if data.get('due_date'):
        try:
            due_date = datetime.fromisoformat(data['due_date'].replace('Z', '+00:00'))
        except:
            pass
    task = Task(
        title=title, description=data.get('description', ''),
        status=data.get('status', 'todo'), priority=data.get('priority', 'medium'),
        project_id=project_id, assignee_id=data.get('assignee_id'),
        created_by=user_id, due_date=due_date
    )
    db.session.add(task)
    db.session.flush()
    log_activity(project_id, user_id, 'task_created', f"Created task '{task.title}'", task_id=task.id, target_user_id=task.assignee_id)
    if task.assignee_id and task.assignee_id != user_id:
        actor = User.query.get(user_id)
        actor_name = actor.name if actor else 'An admin'
        push_notification(
            user_id=task.assignee_id,
            project_id=project_id,
            task_id=None,
            kind='task_assigned',
            message=f"{actor_name} assigned you a task: {title}"
        )
    notify_due_soon_for_task(task)
    db.session.commit()
    return jsonify(task.to_dict()), 201

@app.route('/api/projects/<int:project_id>/tasks/<int:task_id>', methods=['PUT'])
@jwt_required()
def update_task(project_id, task_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id)
    if err: return err, code
    task = Task.query.filter_by(id=task_id, project_id=project_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    role = get_project_role(project_id, user_id)
    if role == 'member' and task.assignee_id != user_id and task.created_by != user_id:
        return jsonify({'error': 'You can only update your own tasks'}), 403
    data = request.get_json()
    old_status = task.status
    old_assignee_id = task.assignee_id
    if role == 'member':
        # Members are only allowed to move task status.
        if 'status' not in data or data.get('status') not in ('todo', 'in_progress', 'done'):
            return jsonify({'error': 'Members can only update task status'}), 400
        task.status = data['status']
    else:
        if 'title' in data and data['title'].strip():
            task.title = data['title'].strip()
        if 'description' in data:
            task.description = data['description']
        if 'status' in data and data['status'] in ('todo', 'in_progress', 'done'):
            task.status = data['status']
        if 'priority' in data and data['priority'] in ('low', 'medium', 'high'):
            task.priority = data['priority']
        if 'assignee_id' in data:
            task.assignee_id = data['assignee_id']
        if 'due_date' in data:
            if data['due_date']:
                try:
                    task.due_date = datetime.fromisoformat(data['due_date'].replace('Z', '+00:00'))
                except:
                    pass
            else:
                task.due_date = None
    task.updated_at = datetime.now(timezone.utc)
    actor = User.query.get(user_id)
    actor_name = actor.name if actor else 'A member'
    if old_assignee_id != task.assignee_id and task.assignee_id and task.assignee_id != user_id:
        push_notification(
            user_id=task.assignee_id,
            project_id=project_id,
            task_id=task.id,
            kind='task_assigned',
            message=f"{actor_name} assigned you a task: {task.title}"
        )
    if old_assignee_id != task.assignee_id:
        if task.assignee_id:
            assignee = User.query.get(task.assignee_id)
            assignee_name = assignee.name if assignee else f'User {task.assignee_id}'
            log_activity(project_id, user_id, 'task_reassigned', f"Reassigned task '{task.title}' to {assignee_name}", task_id=task.id, target_user_id=task.assignee_id)
        else:
            log_activity(project_id, user_id, 'task_reassigned', f"Unassigned task '{task.title}'", task_id=task.id)
    if old_status != task.status:
        log_activity(project_id, user_id, 'task_status_changed', f"Moved task '{task.title}' from {old_status.replace('_', ' ').title()} to {task.status.replace('_', ' ').title()}", task_id=task.id)
        for admin_id in get_admin_user_ids(project_id):
            if admin_id == user_id:
                continue
            push_notification(
                user_id=admin_id,
                project_id=project_id,
                task_id=task.id,
                kind='task_status',
                message=f"{actor_name} changed status of '{task.title}' to {task.status.replace('_', ' ').title()}"
            )
    notify_due_soon_for_task(task)
    db.session.commit()
    return jsonify(task.to_dict())

@app.route('/api/projects/<int:project_id>/tasks/<int:task_id>', methods=['DELETE'])
@jwt_required()
def delete_task(project_id, task_id):
    user_id = int(get_jwt_identity())
    project, err, code = require_project_access(project_id, user_id)
    if err: return err, code
    task = Task.query.filter_by(id=task_id, project_id=project_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    role = get_project_role(project_id, user_id)
    if role == 'member' and task.created_by != user_id:
        return jsonify({'error': 'Only admins or task creator can delete tasks'}), 403
    log_activity(project_id, user_id, 'task_deleted', f"Deleted task '{task.title}'", task_id=task.id)
    db.session.delete(task)
    db.session.commit()
    return jsonify({'message': 'Task deleted'})

@app.route('/api/projects/<int:project_id>/tasks/<int:task_id>/comments', methods=['GET'])
@jwt_required()
def get_task_comments(project_id, task_id):
    user_id = int(get_jwt_identity())
    _, err, code = require_project_access(project_id, user_id)
    if err:
        return err, code
    task = Task.query.filter_by(id=task_id, project_id=project_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    comments = TaskComment.query.filter_by(task_id=task_id, project_id=project_id).order_by(TaskComment.created_at.asc()).all()
    return jsonify([c.to_dict() for c in comments])

@app.route('/api/projects/<int:project_id>/tasks/<int:task_id>/comments', methods=['POST'])
@jwt_required()
def create_task_comment(project_id, task_id):
    user_id = int(get_jwt_identity())
    _, err, code = require_project_access(project_id, user_id)
    if err:
        return err, code
    task = Task.query.filter_by(id=task_id, project_id=project_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'error': 'Comment content is required'}), 400
    if len(content) > 2000:
        return jsonify({'error': 'Comment is too long'}), 400

    comment = TaskComment(task_id=task_id, project_id=project_id, user_id=user_id, content=content)
    db.session.add(comment)
    db.session.flush()
    log_activity(project_id, user_id, 'comment_added', f"Commented on task '{task.title}'", task_id=task.id)

    mentioned_user_ids = [uid for uid in extract_mentioned_user_ids(project_id, content) if uid != user_id]
    current_user = User.query.get(user_id)
    actor_name = current_user.name if current_user else 'Someone'
    for uid in mentioned_user_ids:
        db.session.add(Notification(
            user_id=uid,
            project_id=project_id,
            task_id=task_id,
            comment_id=comment.id,
            kind='mention',
            message=f"{actor_name} mentioned you in task: {task.title}"
        ))

    db.session.commit()
    return jsonify(comment.to_dict()), 201

@app.route('/api/projects/<int:project_id>/activity', methods=['GET'])
@jwt_required()
def get_project_activity(project_id):
    user_id = int(get_jwt_identity())
    _, err, code = require_project_access(project_id, user_id)
    if err:
        return err, code
    role = get_project_role(project_id, user_id)
    if role == 'admin':
        logs = ActivityLog.query.filter_by(project_id=project_id).order_by(ActivityLog.created_at.desc()).limit(120).all()
    else:
        related_task_ids = [
            t.id for t in Task.query.filter(
                Task.project_id == project_id,
                or_(Task.assignee_id == user_id, Task.created_by == user_id)
            ).all()
        ]
        logs = ActivityLog.query.filter(
            ActivityLog.project_id == project_id,
            or_(
                ActivityLog.actor_id == user_id,
                ActivityLog.target_user_id == user_id,
                ActivityLog.task_id.in_(related_task_ids) if related_task_ids else False
            )
        ).order_by(ActivityLog.created_at.desc()).limit(120).all()
    return jsonify([l.to_dict() for l in logs])

# ─── Notification Routes ───────────────────────────────────────────────────────

@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    user_id = int(get_jwt_identity())
    generate_due_soon_notifications_for_user(user_id)
    db.session.commit()
    notifications = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).limit(50).all()
    unread_count = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    return jsonify({
        'unread_count': unread_count,
        'items': [n.to_dict() for n in notifications]
    })

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    user_id = int(get_jwt_identity())
    notification = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if not notification:
        return jsonify({'error': 'Notification not found'}), 404
    notification.is_read = True
    db.session.commit()
    return jsonify({'message': 'Notification marked as read'})

@app.route('/api/notifications/read-all', methods=['PUT'])
@jwt_required()
def mark_all_notifications_read():
    user_id = int(get_jwt_identity())
    Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'message': 'All notifications marked as read'})

# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/api/dashboard', methods=['GET'])
@jwt_required()
def dashboard():
    user_id = int(get_jwt_identity())
    memberships = ProjectMember.query.filter_by(user_id=user_id).all()
    role_by_project = {m.project_id: m.role for m in memberships}
    project_ids = [m.project_id for m in memberships]
    all_tasks = Task.query.filter(Task.project_id.in_(project_ids)).all() if project_ids else []

    visible_tasks = []
    for t in all_tasks:
        role = role_by_project.get(t.project_id)
        if role == 'admin' or t.assignee_id == user_id or t.created_by == user_id:
            visible_tasks.append(t)

    my_tasks = [t for t in visible_tasks if t.assignee_id == user_id]
    overdue = []
    for t in visible_tasks:
        if is_task_overdue(t):
            overdue.append(t)
    return jsonify({
        'total_projects': len(project_ids),
        'total_tasks': len(visible_tasks),
        'my_tasks': len(my_tasks),
        'todo': len([t for t in visible_tasks if t.status == 'todo']),
        'in_progress': len([t for t in visible_tasks if t.status == 'in_progress']),
        'done': len([t for t in visible_tasks if t.status == 'done']),
        'overdue': len(overdue),
        'recent_tasks': [t.to_dict() for t in sorted(visible_tasks, key=lambda x: x.updated_at, reverse=True)[:5]],
        'overdue_tasks': [t.to_dict() for t in overdue[:5]]
    })

def init_database():
    with app.app_context():
        db.create_all()

init_database()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)