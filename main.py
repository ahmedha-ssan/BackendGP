from fastapi import FastAPI, HTTPException
import firebase_admin
from firebase_admin import credentials, db
from firebase_admin import firestore
from typing import List, Dict
from sklearn.neighbors import NearestNeighbors
import numpy as np
import pandas as pd
import traceback
from sklearn.preprocessing import LabelEncoder
from collections import Counter
from datetime import datetime
from models.user_model import NewUser, User
from models.request_model import PredictRequest, PredictMultipleRequest


# Initialize Firebase Admin
cred = credentials.Certificate("ar-furniture-789f5-firebase-adminsdk-w4jtf-53393ec8c3.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://ar-furniture-789f5-default-rtdb.firebaseio.com/'
})

dbs = firestore.client()

app = FastAPI()


@app.get('/')
def index():
    # Reference to the 'users' collection
    collection_ref = dbs.collection("users")

    # Fetch all documents in the collection
    docs = collection_ref.stream()

    # Convert documents to a list of dictionaries
    users: List[Dict] = []
    for doc in docs:
        user_data = doc.to_dict()
        user_data['id'] = doc.id  # Add the document ID to the data
        users.append(user_data)

    return users


@app.post("/users/add-edit/")
def create_user(user: NewUser):
    try:
        # Access the Firestore collection
        user_ref = dbs.collection("users").document(user.user_id)
        user_ref.get()
        if user_ref.get().exists:
            new_or_edit = 1
            user_ref.set(
                user.dict(by_alias=True,
                          exclude={"cart", "comment_and_reviews", "favourite", "history_purchased", "user_id"}))
        else:
            new_or_edit = 0
            user_ref.set(
                user.dict(by_alias=True,
                          exclude={"cart", "comment_and_reviews", "favourite", "history_purchased", "user_id"}))

        # Create collections by default
        user_ref.collection('cart')
        user_ref.collection('comment and reviews')
        user_ref.collection('favourite')
        user_ref.collection('history_purchased')

        if user.cart:
            cart_ref = user_ref.collection('cart')
            for item in user.cart:
                item['date'] = datetime.now()
                cart_ref.document(item['product_id']).set(item)
        if user.comment_and_reviews:
            comments_and_reviews_ref = user_ref.collection('comment and reviews')
            for item in user.comment_and_reviews:
                item['date'] = datetime.now()
                comments_and_reviews_ref.document(item['product_id']).set(item)
        if user.favourite:
            favourite_ref = user_ref.collection('favourite')
            for item in user.favourite:
                item['date'] = datetime.now()
                favourite_ref.document(item['product_id']).set(item)
        if user.history_purchased:
            history_purchased_ref = user_ref.collection('history_purchased')
            for item in user.history_purchased:
                item['date'] = datetime.now()
                history_purchased_ref.document(item['product_id']).set(item)

        if new_or_edit:
            return {"message": "User edited successfully"}
        else:
            return {"message": "User created successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------- Machine Learning --------------------


# Instantiate the KNN NearestNeighbour model
knn = NearestNeighbors(n_neighbors=7)


def fetch_data_from_firebase():
    ref = db.reference('products')
    products = ref.get()
    print("products", products)
    X_train = []
    keys = [
        'category',
        # 'description',
        'material',
        'price',
        # 'productName',
        'sizeX',
        'sizeY',
        'sizeZ',
        'weight'
    ]
    categories = {key: set() for key in ['category', 'material']}
    if products:
        for key, value in products.items():
            for key1 in ['category', 'material']:
                value1 = value.get(key1, 'N/A')
                if value1 != 'N/A':
                    categories[key1].add(value1)
    encoders = {key: LabelEncoder().fit(list(val)) for key, val in categories.items()}
    if products:
        for key, value in products.items():
            product_features = []
            for key1 in keys:
                value1 = value.get(key1, 'N/A')
                if key1 in ['category', 'material']:
                    if value1 != 'N/A':
                        value1 = encoders[key1].transform([value1])[0]
                else:
                    try:
                        value1 = pd.to_numeric(value1)
                    except ValueError:
                        value1 = 0  # default value
                product_features.append(value1)
            X_train.append(product_features)
    print("train", X_train)
    return np.array(X_train)


@app.post("/train/")
async def train():
    try:
        X_train = fetch_data_from_firebase()
        print(X_train)
        knn.fit(X_train)
        return {"status": "training successful"}
    except Exception as e:
        print(f"Exception type: {type(e)}")
        print(f"Exception message: {str(e)}")
        print("Traceback:")
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/predict/")
async def predict(request: PredictRequest):
    try:
        # Transform the features into a numpy array and reshape it
        X_test = np.array(request.features).reshape(1, -1)

        # Get the indices of the nearest neighbors and their distances
        distances, indices = knn.kneighbors(X_test)

        # Get the products from the database
        ref = db.reference('products')
        products = ref.get()
        product_keys = list(products.keys())

        # Prepare the response
        response = []
        for i in range(len(indices[0])):
            index = indices[0][i]
            distance = distances[0][i]
            product = products[product_keys[index]]
            response.append({
                "product": product,
                "distance": distance
            })

        return response
    except Exception as e:
        print(f"Exception type: {type(e)}")
        print(f"Exception message: {str(e)}")
        print("Traceback:")
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/predict_multiple/")
async def predict_multiple(request: PredictMultipleRequest):
    try:
        # Prepare the response
        response = []

        # For each product in the request
        for product_features in request.products:
            # Transform the features into a numpy array and reshape it
            X_test = np.array(product_features).reshape(1, -1)

            # Get the indices of the nearest neighbors and their distances
            distances, indices = knn.kneighbors(X_test)

            # Get the products from the database
            ref = db.reference('products')
            products = ref.get()
            product_keys = list(products.keys())

            # For each neighbor
            for i in range(len(indices[0])):
                index = indices[0][i]
                distance = distances[0][i]
                product = products[product_keys[index]]
                response.append({
                    "product": product,
                    "distance": distance
                })

        return response
    except Exception as e:
        print(f"Exception type: {type(e)}")
        print(f"Exception message: {str(e)}")
        print("Traceback:")
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


def initialize_encoders():
    ref = db.reference('products')
    products = ref.get()
    categories = {key: set() for key in ['category', 'material']}
    if products:
        for key, value in products.items():
            for key1 in ['category', 'material']:
                value1 = value.get(key1, 'N/A')
                if value1 != 'N/A':
                    categories[key1].add(value1)
    encoders = {key: LabelEncoder().fit(list(val)) for key, val in categories.items()}
    return encoders


def predict_by_id(product_id: str):
    try:
        # Initialize encoders
        encoders = initialize_encoders()

        # Get the product from the database
        ref = db.reference(f'products/{product_id}')
        product = ref.get()

        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Extract the features from the product
        keys = ['category', 'material', 'price', 'sizeX', 'sizeY', 'sizeZ', 'weight']
        product_features = []
        for key in keys:
            value = product.get(key, 'N/A')
            if key in ['category', 'material']:
                if value != 'N/A':
                    value = encoders[key].transform([value])[0]
            else:
                try:
                    value = pd.to_numeric(value)
                except ValueError:
                    value = 0  # default value
            product_features.append(value)

        # Transform the features into a numpy array and reshape it
        X_test = np.array(product_features).reshape(1, -1)

        # Get the indices of the nearest neighbors and their distances
        distances, indices = knn.kneighbors(X_test)

        # Get all products from the database
        ref = db.reference('products')
        products = ref.get()
        product_keys = list(products.keys())

        # Prepare the response
        response = []
        for i in range(len(indices[0])):
            index = indices[0][i]
            distance = distances[0][i]
            neighbor_product_id = product_keys[index]
            # Skip the neighbor if its id is the same as the product_id
            if neighbor_product_id == product_id or distance > 1500:
                continue
            neighbor_product = products[neighbor_product_id]
            response.append({
                "product": neighbor_product,
                "distance": distance
            })

        return response
    except Exception as e:
        print(f"Exception type: {type(e)}")
        print(f"Exception message: {str(e)}")
        print("Traceback:")
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/predict_by_id/{product_id}")
async def make_prediction_by_id(product_id: str):
    # Train the Model
    await train()

    return predict_by_id(product_id)


def fetch_user_product_ids(user_id: str):
    collections = ["cart", "comment and reviews", "favourite", "history_purchased"]
    product_ids = []

    for collection in collections:
        # Access the Firestore collection
        doc_ref = dbs.collection("users").document(user_id).collection(collection)
        docs = doc_ref.stream()

        for doc in docs:
            product_ids.append(doc.id)

    # Convert the list of product_ids into a dictionary
    product_ids_dict = dict(Counter(product_ids))

    # Sort the dictionary by count in descending order
    product_ids_dict = dict(sorted(product_ids_dict.items(), key=lambda item: item[1], reverse=True))

    return product_ids_dict


@app.get("/user_products")
async def get_user_products(user: User):
    return fetch_user_product_ids(user.user_id)


@app.get("/user_products_neighbours/{user_id}")
async def get_user_products_neighbours(user_id: str):
    await train()

    # Fetch the product IDs associated with the user
    user_product_ids_dict = fetch_user_product_ids(user_id)

    # Prepare the response
    response = {}

    # Create a list of all product IDs
    all_product_ids = list(user_product_ids_dict.keys())

    # Create a dictionary to store the neighbours
    neighbours_dict = {}

    # For each product ID
    for product_id, count in user_product_ids_dict.items():
        try:
            # Get the nearest neighbors for the product
            neighbours = predict_by_id(product_id)

            # Remove any neighbours that are in the list of all product IDs
            neighbours = [neighbour for neighbour in neighbours if neighbour['product']['id'] not in all_product_ids]

            # Add the neighbours to the dictionary
            for neighbour in neighbours:
                neighbours_dict[neighbour['product']['id']] = neighbour

        except HTTPException as e:
            print(f"Product {product_id} not found. Skipping...")

    # Convert the dictionary of neighbours back to a list
    neighbours_list = list(neighbours_dict.values())

    # Add the neighbours to the response
    response = {
        "neighbours": neighbours_list
    }

    return response

