from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import re
import json
from typing import Dict, Set, List, Any
import itertools
import os

app = Flask(__name__)


app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'tu_clave_secreta_muy_larga_y_segura_12345!@#'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Operation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sets_input = db.Column(db.Text, nullable=False)
    equation = db.Column(db.String(200), nullable=False)
    result = db.Column(db.Text, nullable=False)
    svg_diagram = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class AdvancedSetResolver:
    def __init__(self):
        self.sets: Dict[str, Set] = {}
        self.universo: Set = set()

    def parse_sets(self, sets_text: str) -> Dict[str, Set]:
        self.sets = {}
        lines = sets_text.strip().split('\n')
        for line in lines:
            if '=' not in line:
                continue
            name, values = line.split('=', 1)
            name = name.strip()
            elements = []
            for elem in values.split(','):
                elem = elem.strip()
                if elem:
                    try:
                        if elem.isdigit():
                            elements.append(int(elem))
                        else:
                            elements.append(elem)
                    except:
                        elements.append(elem)
            set_elements = set(elements)
            self.sets[name] = set_elements
            if name.upper() == 'U':
                self.universo = set_elements
            else:
                self.universo.update(set_elements)
        if not any(name.upper() == 'U' for name in self.sets.keys()):
            all_elements = set()
            for s in self.sets.values():
                all_elements.update(s)
            self.universo = all_elements
            self.sets['U'] = all_elements
        return self.sets

    def normalize_expression(self, expr: str) -> str:
        replacements = {
            'U': '∪', 'u': '∪',
            'n': '∩', 'N': '∩',
            '\\': '\\',
            'D': 'Δ', 'd': 'Δ',
            '-': '\\',
            '^': 'Δ',
            'X': '×', 'x': '×',
        }
        normalized = expr
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        return normalized

    def evaluate_expression(self, expression: str) -> Dict[str, Any]:
        try:
            expr = self.normalize_expression(expression.strip())
            if 'P(' in expr or '×' in expr:
                return self._handle_special_operations(expr)
            result_set = self._evaluate_step_by_step(expr)
            return {
                "type": "set",
                "result": sorted(list(result_set), key=str),
                "cardinality": len(result_set)
            }
        except Exception as e:
            raise ValueError(f"Error evaluando expresión: {str(e)}")

    def _evaluate_step_by_step(self, expr: str) -> Set:
        expr = expr.replace(' ', '')
        while '(' in expr and ')' in expr:
            start = expr.rfind('(')
            end = expr.find(')', start)
            if start == -1 or end == -1:
                break
            sub_expr = expr[start + 1:end]
            sub_result = self._evaluate_simple_expression(sub_expr)
            temp_name = f"__TEMP{len(self.sets)}__"
            self.sets[temp_name] = sub_result
            expr = expr[:start] + temp_name + expr[end + 1:]
        return self._evaluate_simple_expression(expr)

    def _evaluate_simple_expression(self, expr: str) -> Set:
        expr = expr.strip()
        if not expr:
            return set()
        operators = ['\\', 'Δ', '∩', '∪']
        for op in operators:
            if op in expr:
                parts = self._split_by_operator(expr, op)
                if len(parts) >= 2:
                    result = self._get_set(parts[0])
                    for i in range(1, len(parts)):
                        right = self._get_set(parts[i])
                        if op == '∪':
                            result = result | right
                        elif op == '∩':
                            result = result & right
                        elif op == '\\':
                            result = result - right
                        elif op == 'Δ':
                            result = result ^ right
                    return result
        return self._get_set(expr)

    def _split_by_operator(self, expr: str, operator: str) -> List[str]:
        parts = []
        current = ""
        i = 0
        while i < len(expr):
            if expr[i:i + len(operator)] == operator:
                parts.append(current)
                current = ""
                i += len(operator)
            else:
                current += expr[i]
                i += 1
        if current:
            parts.append(current)
        return parts

    def _get_set(self, expr: str) -> Set:
        expr = expr.strip()
        if not expr:
            return set()
        if expr.endswith("'"):
            set_name = expr[:-1].strip()
            if set_name in self.sets:
                return self.universo - self.sets[set_name]
            else:
                try:
                    inner_set = self._evaluate_simple_expression(set_name)
                    return self.universo - inner_set
                except:
                    raise ValueError(f"Conjunto '{set_name}' no definido")
        if expr in self.sets:
            return self.sets[expr]
        else:
            if any(op in expr for op in ['∪', '∩', '\\', 'Δ']):
                return self._evaluate_simple_expression(expr)
            else:
                raise ValueError(f"Conjunto '{expr}' no definido")

    def _handle_special_operations(self, expr: str) -> Dict[str, Any]:
        expr = expr.strip()
        powerset_match = re.match(r'P\(([^)]+)\)', expr, re.IGNORECASE)
        if powerset_match:
            set_name = powerset_match.group(1).strip()
            base_set = self._get_set(set_name)
            power_set = [set(subset) for subset in self._powerset(base_set)]
            return {
                "type": "powerset",
                "elements": [f"{{{', '.join(map(str, sorted(list(s), key=str)))}}}" for s in power_set],
                "cardinality": len(power_set),
                "base_set": sorted(list(base_set), key=str)
            }
        if '×' in expr:
            parts = expr.split('×')
            if len(parts) != 2:
                raise ValueError("Formato de producto cartesiano inválido")
            set1_name = parts[0].strip()
            set2_name = parts[1].strip()
            set1 = self._get_set(set1_name)
            set2 = self._get_set(set2_name)
            cartesian = [(a, b) for a in set1 for b in set2]
            return {
                "type": "cartesian",
                "elements": [f"({a}, {b})" for a, b in cartesian],
                "cardinality": len(cartesian),
                "sets": [sorted(list(set1), key=str), sorted(list(set2), key=str)]
            }
        raise ValueError("Operación especial no reconocida")

    def _powerset(self, s: Set) -> List[Set]:
        s_list = list(s)
        return [set(subset) for subset in itertools.chain.from_iterable(
            itertools.combinations(s_list, r) for r in range(len(s_list) + 1)
        )]

    def calculate_venn_data(self, result_set: Set = None) -> Dict[str, Any]:
        if not self.sets:
            return {"regions": {}}
        set_names = [name for name in self.sets.keys() if name.upper() != 'U' and not name.startswith('__TEMP')]
        regions = {}
        all_elements = self.universo
        for element in all_elements:
            membership = []
            for set_name in set_names:
                if element in self.sets[set_name]:
                    membership.append(set_name)
            region_id = ''.join(sorted(membership)) if membership else 'none'
            if region_id not in regions:
                regions[region_id] = {"elements": [], "count": 0}
            regions[region_id]["elements"].append(str(element))
            regions[region_id]["count"] += 1
        for region in regions.values():
            region["elements"] = sorted(region["elements"], key=lambda x: (len(x), x))
        return {
            "regions": regions,
            "set_names": set_names,
            "universo": sorted(list(self.universo), key=str)
        }


def generate_euler_svg(venn_data: Dict[str, Any]) -> str:
    try:
        set_names = venn_data.get("set_names", [])
        if len(set_names) > 4:
            set_names = set_names[:4]
        elif len(set_names) == 0:
            return '<svg width="600" height="100"><text x="50%" y="50%" text-anchor="middle" font-family="Arial">Sin conjuntos</text></svg>'

        default_colors = ["red", "blue", "green", "orange"]
        color_map = {name: default_colors[i] for i, name in enumerate(set_names)}
        standard_keys = ["A", "B", "C", "D"]
        name_to_key = {name: standard_keys[i] for i, name in enumerate(set_names)}

        positions = {
            "A": (180, 200, 90, 60),
            "B": (320, 200, 90, 60),
            "C": (250, 300, 60, 90),
            "D": (250, 100, 60, 90)
        }

        region_positions = {
            "A": (120, 190), "B": (380, 190), "C": (250, 380), "D": (250, 40),
            "AB": (250, 190), "AC": (180, 270), "AD": (180, 130),
            "BC": (320, 270), "BD": (320, 130), "CD": (250, 220),
            "ABC": (250, 250), "ABD": (250, 150), "ACD": (210, 220), "BCD": (290, 220),
            "ABCD": (250, 200), "none": (450, 450)
        }

        svg_lines = [
            '<svg width="600" height="500" xmlns="http://www.w3.org/2000/svg">',
            '  <rect width="100%" height="100%" fill="white"/>'
        ]

        for name in set_names:
            key = name_to_key[name]
            if key in positions:
                cx, cy, rx, ry = positions[key]
                color = color_map[name]
                svg_lines.append(
                    f'  <ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" '
                    f'fill="{color}" fill-opacity="0.2" stroke="{color}" stroke-width="2"/>'
                )
                svg_lines.append(
                    f'  <text x="{cx}" y="{cy - ry - 10}" font-family="Arial" font-size="16" '
                    f'text-anchor="middle" fill="{color}">{name}</text>'
                )

        regions = venn_data.get("regions", {})
        for region_id, data in regions.items():
            if region_id == "none" or not data.get("elements"):
                continue
            sorted_key = ''.join(sorted(region_id))
            if sorted_key in region_positions:
                x, y = region_positions[sorted_key]
                elements_str = ", ".join(str(e) for e in data["elements"])
                svg_lines.append(
                    f'  <text x="{x}" y="{y}" font-family="Arial" font-size="12" '
                    f'text-anchor="middle" fill="black">{elements_str}</text>'
                )

        svg_lines.append('</svg>')
        return "\n".join(svg_lines)

    except Exception as e:
        return '<svg width="600" height="100"><text x="50%" y="50%" text-anchor="middle" font-family="Arial">Error SVG</text></svg>'


resolver = AdvancedSetResolver()


@app.route('/')
def index():
    return render_template('index.html', logged_in=current_user.is_authenticated)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect('/')
        return render_template('login.html', error="Usuario o contraseña incorrectos")
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error="Nombre de usuario ya existe")
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error="Correo ya registrado")
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect('/')
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/')


@app.route('/solve', methods=['POST'])
@login_required
def solve():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No se recibieron datos JSON"})

        sets_text = data.get('sets', '')
        equation = data.get('equation', '')
        if not sets_text or not equation:
            return jsonify({"success": False, "error": "Datos incompletos"})

        sets = resolver.parse_sets(sets_text)
        result_data = resolver.evaluate_expression(equation)
        result_set = set(result_data.get('result', [])) if result_data.get('type') == 'set' else set()
        venn_data = resolver.calculate_venn_data(result_set)
        svg_diagram = generate_euler_svg(venn_data)

        op = Operation(
            user_id=current_user.id,
            sets_input=sets_text,
            equation=equation,
            result=json.dumps(result_data),
            svg_diagram=svg_diagram
        )
        db.session.add(op)
        db.session.commit()

        return jsonify({
            "success": True,
            "results": [result_data],
            "result": result_data.get('result', []),
            "cardinality": result_data.get('cardinality', 0),
            "svg_diagram": svg_diagram
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
