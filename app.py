from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from transformers import pipeline
from datetime import datetime, timezone
from sqlalchemy import func
import re
import os

# Initialize NLP pipelines
sentiment_analyzer = pipeline("text-classification", model="cardiffnlp/twitter-roberta-base-sentiment-latest")
emotion_analyzer = pipeline("text-classification", model="SamLowe/roberta-base-go_emotions", top_k=None)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['DEBUG'] = True
app.jinja_env.auto_reload = True
app.jinja_env.cache = {}
app.config['SECRET_KEY'] = os.urandom(24).hex()
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vibechecker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    analyses = db.relationship('AnalysisHistory', backref='user', lazy=True)

class AnalysisHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    results = db.Column(db.JSON, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Emotion Configuration
EMOJI_MAP = {
    "sentiment": {"negative": "😠", "neutral": "😐", "positive": "😊"},
    "emotion": {
        "admiration": "🤩", "amusement": "😄", "anger": "😠", "annoyance": "😒",
        "approval": "👍", "caring": "❤️", "confusion": "😕", "curiosity": "🧐",
        "desire": "😍", "disappointment": "😞", "disapproval": "👎", "disgust": "🤢",
        "embarrassment": "😳", "excitement": "🎉", "fear": "😨", "gratitude": "🙏",
        "grief": "😢", "joy": "😊", "love": "💖", "nervousness": "😬", "optimism": "🌈",
        "pride": "🦁", "realization": "💡", "relief": "😌", "remorse": "😔",
        "sadness": "😞", "surprise": "😲", "neutral": "😐"
    }
}

EMOTION_ADJUSTMENT_RULES = {
    'sentiment': {
        'positive': {'boost': ['joy', 'love', 'optimism'], 'reduce': ['anger', 'annoyance']},
        'negative': {'boost': ['anger', 'annoyance'], 'reduce': ['joy', 'love']},
        'neutral': {'boost': ['curiosity', 'confusion'], 'reduce': ['pride', 'gratitude']}
    }
}

def adjust_emotions(emotions, sentiment_label):
    emotions = [{'label': e['label'].lower(), 'score': e['score']} for e in emotions]
    sentiment_rules = EMOTION_ADJUSTMENT_RULES['sentiment'].get(sentiment_label, {})
    for e in emotions:
        if e['label'] in sentiment_rules.get('boost', []): e['score'] *= 1.6
        if e['label'] in sentiment_rules.get('reduce', []): e['score'] *= 0.3
    total = sum(e['score'] for e in emotions)
    return sorted([{'label': e['label'], 'score': max(0, min(1, e['score'] / total))}
                  for e in emotions if e['score'] >= 0.05], key=lambda x: x['score'], reverse=True)[:5]

# Routes
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/analysis', methods=['GET', 'POST'])
def analysis():
    if request.method == 'POST':
        text = request.form.get('text', '').strip()[:500]
        if len(text) < 10:
            flash('Text must be at least 10 characters', 'danger')
            return redirect(url_for('analysis'))
        try:
            sentiment = sentiment_analyzer(text)[0]
            raw_emotions = emotion_analyzer(text)[0]
            emotions = adjust_emotions([{'label': e['label'], 'score': e['score']} for e in raw_emotions], sentiment['label'])
            results = {
                'sentiment': {
                    'label': sentiment['label'],
                    'emoji': EMOJI_MAP['sentiment'][sentiment['label']],
                    'score': round(sentiment['score'] * 100, 1)
                },
                'emotions': [{
                    'label': e['label'],
                    'emoji': EMOJI_MAP['emotion'][e['label']],
                    'score': round(e['score'] * 100, 1)
                } for e in emotions]
            }
            if current_user.is_authenticated:
                analysis = AnalysisHistory(text=text, results=results, user_id=current_user.id)
                db.session.add(analysis)
                db.session.commit()
            return render_template('analysis.html', results=results, text=text)
        except Exception as e:
            app.logger.error(f"Analysis error: {str(e)}")
            flash('Analysis failed. Please try again.', 'danger')
    return render_template('analysis.html')

@app.route('/history')
def history():
    if current_user.is_authenticated:
        analyses = AnalysisHistory.query.filter_by(user_id=current_user.id).order_by(AnalysisHistory.timestamp.desc()).all()
    else:
        analyses = []  # Empty list for non-logged-in users
    return render_template('history.html', analyses=analyses)

@app.route('/history/<int:analysis_id>')
@login_required
def analysis_detail(analysis_id):
    analysis = AnalysisHistory.query.get_or_404(analysis_id)
    if analysis.user != current_user: abort(403)
    return render_template('analysis_detail.html', results=analysis.results, text=analysis.text)

@app.route('/delete_analysis/<int:analysis_id>', methods=['POST'])
@login_required
def delete_analysis(analysis_id):
    analysis = AnalysisHistory.query.get_or_404(analysis_id)
    if analysis.user != current_user: abort(403)
    db.session.delete(analysis)
    db.session.commit()
    flash('Analysis deleted successfully', 'success')
    return redirect(url_for('history'))

@app.route('/clear_history', methods=['POST'])
@login_required
def clear_history():
    AnalysisHistory.query.filter_by(user=current_user).delete()
    db.session.commit()
    flash('All history cleared', 'success')
    return redirect(url_for('history'))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/toggle-theme', methods=['POST'])
def toggle_theme():
    theme = request.json.get('theme')
    response = jsonify({'success': True})
    response.set_cookie('theme', theme, max_age=30*24*60*60)
    return response

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('analysis'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
        if not user: flash('Invalid username', 'danger')
        elif not check_password_hash(user.password, password): flash('Incorrect password', 'danger')
        else:
            login_user(user)
            return redirect(url_for('analysis'))
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated: return redirect(url_for('analysis'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if len(username) < 4: flash('Username must be at least 4 characters', 'danger')
        elif User.query.filter(func.lower(User.username) == func.lower(username)).first():
            flash('Username already taken', 'danger')
        else:
            if not re.search(r'[A-Z]', password): flash('Password needs uppercase', 'danger')
            elif not re.search(r'[a-z]', password): flash('Password needs lowercase', 'danger')
            elif not re.search(r'\d', password): flash('Password needs number', 'danger')
            elif not re.search(r'[@$!%*?&]', password): flash('Password needs special character', 'danger')
            else:
                try:
                    new_user = User(username=username, password=generate_password_hash(password))
                    db.session.add(new_user)
                    db.session.commit()
                    login_user(new_user)
                    return redirect(url_for('analysis'))
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"Signup error: {str(e)}")
                    flash('Account creation failed', 'danger')
        return redirect(url_for('signup'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)