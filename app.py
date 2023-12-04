from flask import Flask, render_template, session, redirect, request, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
import os
from pysimilar import compare
from flask_mysqldb import MySQL
import MySQLdb.cursors
from hashlib import sha256

app = Flask(__name__)
app.secret_key = "ExampleSecretKey"
app.config['UPLOAD_FOLDER'] = "uploads"
ALLOWED_EXTENSIONS = { 'pdf' }

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'sarim'
app.config['MYSQL_PASSWORD'] = '12345678'
app.config['MYSQL_DB'] = 'fse'
mysql = MySQL(app)

def query(q : str, t : tuple, l = True, d=True):
    if d:
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    else:
        cur = mysql.connection.cursor()
    cur.execute(q, t)
    if l:
        res = cur.fetchall()
    else:
        res = cur.fetchone()
    cur.close()
    return res
def get_col_names(table_name):
    col = query("select column_name \
        from information_schema.columns \
        where table_schema=%s and table_name=%s order by ordinal_position", 
        (app.config['MYSQL_DB'], table_name), True, False
    )
    col = [c[0] for c in col]
    return col
def allowed_file(filename : str):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def add_or_overwrite_submission(assignment_id, ext):
    res = query("SELECT * FROM SUBMISSION WHERE assignment_id=%s and student_id=%s", (assignment_id, session['user']['id']), False)
    if res:
        query("UPDATE SUBMISSION SET ext=%s, submitted_on=SYSDATE() WHERE assignment_id=%s and student_id=%s", (ext, assignment_id, session['user']['id']))
    else:
        query("INSERT INTO SUBMISSION VALUES(%s, %s, %s, SYSDATE())", (session['user']['id'], assignment_id, ext))
    mysql.connection.commit()


@app.route('/login', methods=['GET','POST'])
def login():
    if 'user' in session:
        return redirect('/')
    if request.method == "GET":
        return render_template('login.html', hide_logout=True)
    
    f = request.form.to_dict()
    password_hash = int(sha256(f['password'].encode('ascii')).hexdigest(), 16) % 2147483647
    print(f['password'], password_hash)

    user = query("SELECT * FROM USER WHERE username=%s", (f['username'],), False)
    if not user:
        flash('ID Does Not Exist')
        return render_template('login.html', hide_logout=True)
    if user['role'] != f['role']:
        flash('Incorrect Role Selection')
        return render_template('login.html', hide_logout=True)
    if user['password_hash'] != password_hash:
        flash('Incorrect Username or Password')
        return render_template('login.html', hide_logout=True)

    session['user'] = user
    return redirect(url_for('home'))

@app.route('/signup', methods=['GET','POST'])
def signup():
    if 'user' in session:
        return redirect('/')
    if request.method == 'GET':
        return render_template('signup.html', hide_logout=True)
    
    f = request.form.to_dict()
    id = f['id']
    username = f['username']
    password_hash = int(sha256(f['password'].encode('ascii')).hexdigest(), 16) % 2147483647
    role = f['role']
    if(role != 's' and role != 't'):
        flash('Incorrect Role Selection')
        return render_template('signup.html', existing=f, hide_logout=True)

    try:
        query("INSERT INTO USER VALUES(%s,%s,%s,%s)", (id, username, password_hash, role))
        mysql.connection.commit()
    except MySQLdb.Error as e:
        flash(e.args)
        return render_template('signup.html', existing=f, hide_logout=True)
    
    return redirect('/login')

@app.route('/logout')
def logout():
    if 'user' in session:
        session.pop('user')
    return redirect('/')

@app.route("/", methods=['GET', 'POST'])
def home():
    if 'user' not in session:
        return redirect('/login')

    if session['user']['role'] == 's':
        classes = query("SELECT * FROM CLASS c INNER JOIN STUDENT_CLASS sc ON c.id=sc.class_id WHERE sc.student_id=%s", (session['user']['id'],))
    else:
        classes = query("SELECT * FROM CLASS WHERE teacher_id=%s", (session['user']['id'],))
    return render_template("home.html", classes=classes)

@app.route('/classes/<int:id>')
def class_view(id):
    if 'user' not in session:
        return redirect('/login')
    
    _class = query("SELECT * FROM CLASS WHERE id=%s", (id,), False)
    if session['user']['role'] == 't':
        if _class['teacher_id'] == session['user']['id']:
            assignments = query("SELECT * FROM ASSIGNMENT WHERE class_id=%s", (id,))
            return render_template('class.html', _class=_class, assignments=assignments)
        return "Forbidden",403
    
    student_class = query("SELECT * FROM STUDENT_CLASS WHERE class_id=%s and student_id=%s", (id, session['user']['id']), False)
    if student_class:
        assignments = query("SELECT * FROM ASSIGNMENT WHERE class_id=%s", (id,))
        return render_template('class.html', _class=_class, assignments=assignments)
    return "Forbidden",403

@app.route('/assignments/<int:id>', methods=['GET','POSt'])
def assignment_view(id):
    if 'user' not in session:
        return redirect('/login')
    
    assignment = query("SELECT * FROM ASSIGNMENT WHERE id=%s", (id,), False)
    if not assignment:
        return "Not Found",404

    # student view
    if session['user']['role'] == 's':
        c_id = query("SELECT class_id FROM ASSIGNMENT WHERE id=%s", (id,), False, False)
        
        if not query("SELECT * FROM STUDENT_CLASS WHERE class_id=%s AND student_id=%s", (c_id, session['user']['id']), False):
            return "Forbidden",403
        
        if request.method == 'GET':
            return render_template('assignment_student.html', assignment=assignment)
        
        if assignment['status'] == 'o':
            file = request.files['submission']
            if allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = str(id) + '_' + str(session['user']['id']) + '.' + ext
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                add_or_overwrite_submission(id, ext)
            else:
                flash("File Type not supported")
        else:
            flash("Submissions closed by teacher")

        return render_template('assignment_student.html', assignment=assignment)
    
    # teacher view
    submissions = query("SELECT * FROM SUBMISSION WHERE assignment_id=%s", (id,))
    return render_template('assignment_teacher.html', assignment=assignment, submissions=submissions)

@app.route('/assignments/<int:a_id>/submissions/<int:s_id>/<ext>/download')
def download(a_id, s_id, ext):
    filename = str(a_id) + '_' + str(s_id) + '.' + ext
    path = os.path.join(app.config['UPLOAD_FOLDER'])
    return send_from_directory(directory=path, path=filename)

@app.route('/plag-check/<int:assignment_id>', methods=['POST'])
def plag_checker(assignment_id):
    if 'user' not in session:
        return redirect('/login')

    submissions = query("SELECT * FROM SUBMISSION WHERE assignment_id=%s", (assignment_id,))
    # generate pairs
    pairs = []
    for i in range(len(submissions)):
        for j in range(i + 1, len(submissions)):
            pairs.append([submissions[i], submissions[j]])
    
    # compare
    indices = []
    for i in range(len(pairs)):
        pair = pairs[i]
        file1 = 'uploads/' + str(pair[0]['assignment_id']) + '_' + str(pair[0]['student_id']) + '.' + pair[0]['ext']
        file2 = 'uploads/' + str(pair[1]['assignment_id']) + '_' + str(pair[1]['student_id']) + '.' + pair[0]['ext']
        res = compare(file1, file2, isfile=True)
        print(res)
        if res < 0.8:
            indices.append(i)
    
    indices.reverse()
    for index in indices:
        pairs.pop(index)

    return render_template('plag_results.html', pairs = pairs, x=0.8*100)

@app.route("/classes/add", methods=['GET','POST'])
def add_class():
    if request.method == 'GET':
        if session['user']['role'] == 't':
            return render_template(
                'forms/form.html', table_name='CLASS', columns=get_col_names('CLASS'), 
                post_addr=url_for('add_class'),existing=None
            )
        return render_template('forms/student_class_form.html', existing=None)
    
    try:
        if session['user']['role'] == 't':
            classname = request.form['name']
            if classname == '':
                classname = None
            query("INSERT INTO CLASS VALUES(%s,%s,%s)", (0, classname, session['user']['id']))
        else:
            class_id = request.form['class-id']
            query("INSERT INTO STUDENT_CLASS VALUES(%s,%s)", (session['user']['id'],class_id))
    except MySQLdb.Error as e:
        flash(e.args[1])
        if session['user']['role'] == 't':
            return render_template(
                'forms/form.html', table_name='CLASS', columns=get_col_names('CLASS'), 
                post_addr=url_for('add_class'),existing=None
            )
        return render_template('forms/student_class_form.html', existing=None)
    mysql.connection.commit()
    return redirect(url_for('home'))

@app.route('/classes/<int:class_id>/assignments/add', methods=['GET', 'POST'])
def add_assignment(class_id):
    if 'user' not in session:
        return redirect('login')
    if session['user']['role'] == 's':
        return "Forbidden",403
    
    classes = query("SELECT * FROM CLASS WHERE teacher_id=%s", (session['user']['id'],))
    if request.method == 'GET':
        existing = { 'class_id':class_id }
        return render_template('forms/assignment_form.html', existing=existing, classes=classes, post_addr=url_for('add_assignment', class_id=class_id))
    
    f = request.form.to_dict()
    due = f['due']
    if due == '':
        due = None
    try:
        query("INSERT INTO ASSIGNMENT VALUES(%s,%s,%s,%s,%s,%s)", (None, f['class-id'], f['name'], f['status'], due, f['description']))
        mysql.connection.commit()
    except MySQLdb.Error as e:
        flash(e.args[1])
        return render_template('forms/assignment_form.html', existing=f, classes=classes, post_addr=url_for('add_assignment', class_id=class_id))
    return redirect(url_for('class_view', id=class_id))

if __name__ == "__main__":
    app.run()
