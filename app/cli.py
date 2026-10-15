"""Flask CLI commands: ``flask --app run <command>``.

    init-db           apply migrations (creates all tables)
    seed-demo         insert clearly labelled SAMPLE data and demo accounts (refuses if users exist)
    create-admin      create an administrator account interactively
    recompute-scores  refresh cached match scores
"""
import random
from datetime import date, timedelta

import click
from flask import current_app

from app.extensions import db
from app.models import (Application, CompanyProfile, Internship, InternshipStatus, Resume, Role, StudentProfile,
                        User)

DEMO_PASSWORDS = {"admin": "Admin@123", "student": "Student@123", "company": "Company@123"}


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create / upgrade all database tables via migrations."""
        from flask_migrate import upgrade
        upgrade()
        click.echo("Database is up to date.")

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True, default="Placement Cell Admin")
    @click.password_option()
    def create_admin(email, name, password):
        """Create an administrator account."""
        from app.utils.validators import password_problems, valid_email
        email = email.strip().lower()
        if not valid_email(email):
            raise click.ClickException("Invalid email.")
        problems = password_problems(password)
        if problems:
            raise click.ClickException(" ".join(problems))
        if User.query.filter_by(email=email).first():
            raise click.ClickException("A user with this email already exists.")
        u = User(email=email, name=name, role=Role.ADMIN)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Admin {email} created.")

    @app.cli.command("seed-demo")
    @click.option("--force", is_flag=True, help="Seed even if users already exist (never deletes data).")
    def seed_demo(force):
        """Insert SAMPLE data for local demos and testing."""
        if User.query.first() and not force:
            raise click.ClickException("Database already has users; refusing to seed. Use --force to add anyway.")
        seed(verbose=True)

    @app.cli.command("recompute-scores")
    def recompute_scores():
        from app.services.match_service import refresh_all
        n = refresh_all()
        db.session.commit()
        click.echo(f"Recomputed scores for {n} application(s).")


# --------------------------------------------------------------------------- sample data
COMPANIES = [
    ("Nimbus Labs (Sample)", "Software Products", "Bengaluru", "Cloud-native SaaS products for small businesses.", True),
    ("DataWeave Analytics (Sample)", "Analytics", "Pune", "Data analytics and ML consulting.", True),
    ("Pixel Forge Studio (Sample)", "Design & Media", "Indore", "Product design and mobile apps studio.", True),
    ("SecureNet Systems (Sample)", "Cybersecurity", "Hyderabad", "Managed security services provider.", False),
]

INTERNSHIPS = [
    # company idx, title, domain, location, mode, weeks, stipend, seats, min_cgpa, depts, years, required, preferred, desc
    (0, "Full Stack Web Developer Intern", "Web Development", "Bengaluru", "Hybrid", 12, 15000, 2, 6.5, None, "3,4",
     "Python, Flask, JavaScript, HTML, CSS, SQL", "React, Git, Docker",
     "Build features for our customer portal using Flask REST APIs, JavaScript and a SQL database. "
     "You will write tests, review code and ship to production with the team."),
    (0, "Cloud & DevOps Intern", "Cloud & DevOps", "Remote", "Remote", 10, 12000, 1, None, None, None,
     "Linux, Docker, Git", "AWS, Kubernetes, CI/CD, Python",
     "Automate deployments, containerise services with Docker and help maintain CI/CD pipelines on AWS."),
    (0, "Backend Java Developer Intern", "Web Development", "Bengaluru", "On-site", 8, 10000, 1, 7.0, None, None,
     "Java, Spring Boot, SQL", "REST API, Git",
     "Develop backend microservices in Java Spring Boot with relational databases and REST APIs."),
    (1, "Machine Learning Intern", "Machine Learning", "Pune", "Hybrid", 12, 20000, 2, 7.5,
     "Computer Science, Information Technology, Data Science", "3,4",
     "Python, Machine Learning, Pandas, Scikit-learn", "Deep Learning, SQL, Statistics",
     "Train and evaluate machine learning models on customer data, perform feature engineering with Pandas "
     "and deploy models with scikit-learn pipelines."),
    (1, "Data Analyst Intern", "Data Science", "Pune", "On-site", 8, 12000, 2, None, None, None,
     "SQL, Excel, Data Analysis", "Power BI, Tableau, Python, Statistics",
     "Analyse sales data, build dashboards in Power BI and present insights to business teams."),
    (1, "NLP Research Intern", "Machine Learning", "Remote", "Remote", 16, 18000, 1, 8.0, None, "4",
     "Python, Natural Language Processing, Machine Learning", "PyTorch, Deep Learning, Generative AI",
     "Research text classification and information extraction using NLP and transformer models."),
    (2, "UI/UX Design Intern", "UI/UX Design", "Indore", "On-site", 8, 8000, 1, None, None, None,
     "Figma, UI/UX Design", "Adobe XD, Photoshop, HTML, CSS",
     "Design wireframes and high fidelity prototypes in Figma for mobile and web apps; run usability tests."),
    (2, "Android App Developer Intern", "Mobile Development", "Indore", "Hybrid", 10, 10000, 2, 6.0, None, None,
     "Android, Kotlin", "Java, Git, REST API, Flutter",
     "Build and publish Android apps in Kotlin, integrate REST APIs and fix bugs reported by users."),
    (2, "Flutter Developer Intern", "Mobile Development", "Remote", "Remote", 8, None, 1, None, None, None,
     "Flutter", "Android, Git, UI/UX Design",
     "Create cross-platform mobile screens with Flutter and Dart for our design clients."),
    (0, "Software Testing (QA) Intern", "Software Testing", "Bengaluru", "On-site", 8, 8000, 1, None, None, None,
     "Software Testing", "Selenium, Python, SQL, Unit Testing",
     "Write test cases, automate regression tests with Selenium and report defects."),
]

STUDENTS = [
    # name, dept, year, cgpa, domain, location, skills, interests, projects
    ("Aarav Sharma", "Computer Science", 4, 8.7, "Machine Learning", "Pune",
     "Python, Machine Learning, Pandas, Scikit-learn, SQL, Statistics",
     "AI research, data science, natural language processing",
     "Built a sentiment analysis model with scikit-learn and NLP; churn prediction with Pandas and Python."),
    ("Diya Patel", "Information Technology", 3, 8.1, "Web Development", "Bengaluru",
     "Python, Flask, JavaScript, HTML, CSS, SQL, Git",
     "Web development, backend APIs, open source",
     "Developed a college event portal using Flask, JavaScript and MySQL with REST APIs."),
    ("Rohan Verma", "Computer Science", 3, 7.2, "Web Development", "Bengaluru",
     "Java, Spring Boot, SQL, Git, REST API",
     "Backend engineering, distributed systems",
     "Library management system in Java Spring Boot with a MySQL database and REST APIs."),
    ("Ananya Iyer", "Electronics", 4, 9.1, "Data Science", "Pune",
     "Python, Data Analysis, Excel, Power BI, SQL, Statistics",
     "Business analytics, dashboards, visualisation",
     "Sales dashboard in Power BI; exploratory data analysis of retail data in Python."),
    ("Kabir Singh", "Computer Science", 2, 6.4, "Mobile Development", "Indore",
     "Android, Kotlin, Java, Git",
     "Mobile apps, Android development",
     "Expense tracker Android app in Kotlin published on the Play Store."),
    ("Meera Nair", "Design", 3, 7.9, "UI/UX Design", "Indore",
     "Figma, UI/UX Design, Photoshop, HTML, CSS",
     "Product design, user research",
     "Redesigned the college website in Figma; ran usability tests with 20 students."),
    ("Ishaan Gupta", "Information Technology", 4, 7.6, "Cloud & DevOps", "",
     "Linux, Docker, AWS, Python, Git, CI/CD",
     "Cloud computing, automation, DevOps",
     "Containerised a Flask app with Docker and deployed it to AWS EC2 using GitHub Actions."),
    ("Sneha Reddy", "Computer Science", 4, 8.9, "Machine Learning", "",
     "Python, Natural Language Processing, Machine Learning, PyTorch, Deep Learning",
     "NLP, generative AI, research",
     "Fine-tuned a transformer for question answering in PyTorch; resume parser with NLP."),
    ("Vikram Joshi", "Mechanical", 3, 6.8, "Software Testing", "Bengaluru",
     "Software Testing, Selenium, Python",
     "Quality assurance, automation",
     "Automated UI tests for a demo e-commerce site using Selenium and Python."),
    ("Priya Menon", "Computer Science", 3, None, "Web Development", "",
     "HTML, CSS, JavaScript",
     "Frontend development",
     ""),
    ("Arjun Das", "Information Technology", 4, 7.4, "Mobile Development", "Remote",
     "Flutter, Android, Git, Firebase",
     "Cross-platform apps",
     "Food delivery app built with Flutter and Firebase."),
    ("Nisha Kulkarni", "Data Science", 3, 8.3, "Data Science", "Pune",
     "Python, SQL, Tableau, Data Visualization, Excel",
     "Analytics, storytelling with data",
     "COVID-19 dashboard in Tableau; SQL analysis of college placement data."),
]


def seed(verbose=False):
    from app.services import match_service
    from app.services.forms import apply_internship, set_student_skills
    from app.services.notifications import notify
    from app.services.resume import process_pdf, resolve_path, store_file
    from app.utils.pdfgen import make_pdf

    def say(msg):
        if verbose:
            click.echo(msg)

    rng = random.Random(42)
    admin = User(email="admin@demo.local", name="Placement Cell Admin (Sample)", role=Role.ADMIN)
    admin.set_password(DEMO_PASSWORDS["admin"])
    db.session.add(admin)

    companies = []
    for n, (name, industry, loc, desc, verified) in enumerate(COMPANIES, start=1):
        u = User(email=f"company{n}@demo.local", name=f"HR Team {n}", role=Role.COMPANY)
        u.set_password(DEMO_PASSWORDS["company"])
        db.session.add(u)
        db.session.flush()
        c = CompanyProfile(user_id=u.id, company_name=name, industry=industry, location=loc, description=desc,
                           contact_person=f"HR Team {n}", website=None, is_verified=verified)
        db.session.add(c)
        companies.append(c)
    db.session.flush()

    internships = []
    for row in INTERNSHIPS:
        (ci, title, domain, loc, mode, weeks, stipend, seats, min_cgpa, depts, years, req, pref, desc) = row
        i = Internship(company_id=companies[ci].id, status=InternshipStatus.PUBLISHED)
        db.session.add(i)
        apply_internship(i, {
            "title": title, "description": desc + " [Sample internship for demonstration]", "domain": domain,
            "location": loc, "work_mode": mode, "duration_weeks": weeks, "stipend": stipend, "seats": seats,
            "min_cgpa": min_cgpa, "eligible_departments": depts, "eligible_years": years,
            "deadline": date.today() + timedelta(days=rng.randint(10, 45)),
            "required_skills": [s.strip() for s in req.split(",")],
            "preferred_skills": [s.strip() for s in pref.split(",")],
        })
        internships.append(i)
    db.session.flush()

    students = []
    for n, (name, dept, year, cgpa, domain, loc, skills, interests, projects) in enumerate(STUDENTS, start=1):
        u = User(email=f"student{n}@demo.local", name=name, role=Role.STUDENT)
        u.set_password(DEMO_PASSWORDS["student"])
        db.session.add(u)
        db.session.flush()
        p = StudentProfile(user_id=u.id, roll_number=f"DEMO{2024000 + n}", degree="B.Tech", department=dept,
                           year_of_study=year, graduation_year=2025 + (4 - year), cgpa=cgpa,
                           interests=interests, projects=projects or None, preferred_domain=domain,
                           preferred_location=loc or None, phone=f"+91-90000000{n:02d}")
        db.session.add(p)
        db.session.flush()
        set_student_skills(p, [s.strip() for s in skills.split(",")])
        if n <= 6:  # sample resumes for some students
            pdf = make_pdf([f"{name} - SAMPLE RESUME (demo data)", f"B.Tech {dept}, CGPA {cgpa or 'N/A'}",
                            "Skills: " + skills, "Projects: " + (projects or "-"),
                            "Interests: " + interests, "Comfortable with Git and teamwork."])
            stored = store_file(pdf)
            res = process_pdf(resolve_path(stored))
            p.resume = Resume(original_filename=f"sample_resume_{n}.pdf", stored_filename=stored,
                              size_bytes=len(pdf), extracted_text=res["text"] or None,
                              extracted_skills=",".join(res["skills"]), extraction_status=res["status"],
                              extraction_message=res["message"])
        students.append(p)
    db.session.flush()

    # Students apply to their top recommendations (realistic preferences).
    for p in students[:-1]:  # last student has not applied yet
        recs = match_service.recommendations(p, limit=3)
        for rank, (i, r) in enumerate(recs, start=1):
            db.session.add(Application(student_id=p.id, internship_id=i.id, preference_rank=rank,
                                       cover_note="I am interested in this role. (sample application)"))
        if recs:
            notify(p.user, "Welcome to the internship portal",
                   "This is sample data. Explore recommendations and track your applications.", "info")
    db.session.commit()
    say(f"Seeded SAMPLE data: {len(companies)} companies, {len(internships)} internships, "
        f"{len(students)} students, {Application.query.count()} applications.")
    say("Demo logins (local testing only - change before any deployment):")
    say(f"  admin@demo.local     / {DEMO_PASSWORDS['admin']}")
    say(f"  company1@demo.local  / {DEMO_PASSWORDS['company']}   (company1..4; company4 is unverified)")
    say(f"  student1@demo.local  / {DEMO_PASSWORDS['student']}   (student1..12)")
    return {"companies": companies, "internships": internships, "students": students, "admin": admin,
            "upload_folder": current_app.config["UPLOAD_FOLDER"]}
