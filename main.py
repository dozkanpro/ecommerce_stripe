from flask import Flask, abort, render_template, redirect, url_for, flash, request
from flask_bootstrap import Bootstrap5
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import stripe
from forms import RegisterForm, LoginForm
import os


stripe.api_key = os.environ.get('stripe_secret_key')

app = Flask(__name__)
app.config['SECRET_KEY'] = '3DYBkEfBA6O6dmnzWlsiHBXox7C0sKR5b'
Bootstrap5(app)

# Configure Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.get_or_404(User, user_id)


# Configure Database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///products.db'
db = SQLAlchemy()
db.init_app(app)


class Products(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    img_url = db.Column(db.String(250), nullable=False)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    name = db.Column(db.String(100))
    cart = db.relationship('Cart', backref='user', lazy=True)


class Cart(db.Model):
    __tablename__ = "cart"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)


with app.app_context():
    db.create_all()


# Register new users into the User database
@app.route('/register', methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():

        # Check if user email is already present in the database.
        result = db.session.execute(db.select(User).where(User.email == form.email.data))
        user = result.scalar()
        if user:
            # User already exists
            flash("You've already signed up with that email, log in instead!")
            return redirect(url_for('login'))

        hash_and_salted_password = generate_password_hash(
            form.password.data,
            method='pbkdf2:sha256',
            salt_length=8
        )
        new_user = User(
            email=form.email.data,
            name=form.name.data,
            password=hash_and_salted_password,
        )
        db.session.add(new_user)
        db.session.commit()
        # This line will authenticate the user with Flask-Login
        login_user(new_user)
        return redirect(url_for("get_all_products"))
    return render_template("register.html", form=form, current_user=current_user)


@app.route('/login', methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        password = form.password.data
        result = db.session.execute(db.select(User).where(User.email == form.email.data))
        # Note, email in db is unique so will only have one result.
        user = result.scalar()
        # Email doesn't exist
        if not user:
            flash("That email does not exist, please try again.")
            return redirect(url_for('login'))
        # Password incorrect
        elif not check_password_hash(user.password, password):
            flash('Password incorrect, please try again.')
            return redirect(url_for('login'))
        else:
            login_user(user)
            return redirect(url_for('get_all_products'))

    return render_template("login.html", form=form, current_user=current_user)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('get_all_products'))


@app.route('/')
def get_all_products():
    result = db.session.execute(db.select(Products))
    products = result.scalars().all()
    return render_template("index.html", all_products=products)


@app.route('/post/<int:product_id>')
def show_product(product_id):
    requested_product = db.get_or_404(Products, product_id)
    return render_template("post.html", product=requested_product, current_user=current_user)


@app.route('/cart')
def show_cart():
    if not current_user.is_authenticated:
        flash("Please log in to view your cart.")
        return redirect(url_for('login'))

    # Retrieve the user's cart items from the database
    cart_items = db.session.query(Cart, Products).join(Products).filter(Cart.user_id == current_user.id).all()
    total_price = 0
    quantity = 0
    for cart_item, product in cart_items:
        total_price += float(product.price) * cart_item.quantity
        quantity += cart_item.quantity

    return render_template("cart.html", current_user=current_user, cart_items=cart_items, total_price=total_price,
                           quantity=quantity)


@app.route('/cart/<int:product_id>', methods=["GET", "POST"])
def cart(product_id):
    if not current_user.is_authenticated:
        flash("Please log in to add products to your cart.")
        return redirect(url_for('login'))

    requested_product = db.get_or_404(Products, product_id)

    # Check if the product is already in the user's cart
    cart_item = Cart.query.filter_by(user_id=current_user.id, product_id=product_id).first()

    if cart_item:
        # If the product is already in the cart, increment the quantity
        cart_item.quantity += 1
    else:
        # If the product is not in the cart, add it with quantity 1
        new_cart_item = Cart(user_id=current_user.id, product_id=product_id, quantity=1)
        db.session.add(new_cart_item)

    db.session.commit()

    flash(f"{requested_product.name} added to your cart.")
    return redirect(url_for('show_cart'))


@app.route('/checkout', methods=["GET", "POST"])
def checkout():
    cart_items = db.session.query(Cart, Products).join(Products).filter(Cart.user_id == current_user.id).all()
    line_items = []

    for cart_item, product in cart_items:
        line_items.append({'price': product.id, "quantity": cart_item.quantity})
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=url_for('success', _external=True),
            cancel_url=url_for('checkout', _external=True),
        )

    except Exception as e:
        return str(e)

    return redirect(checkout_session.url, code=303)


@app.route('/success')
def success():
    # Clear the user's cart in the database
    # Add logic to handle other post-payment actions if needed
    return render_template("success.html")


@app.route('/remove_from_cart/<int:product_id>')
def remove_from_cart(product_id):
    cart_item = Cart.query.filter_by(user_id=current_user.id, product_id=product_id).first()
    if cart_item:
        db.session.delete(cart_item)
        db.session.commit()
    return redirect(url_for('show_cart'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
