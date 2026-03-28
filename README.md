# Project Description 
This Django-based eCommerce platform delivers a dynamic, responsive shopping experience with in-page content updates powered by HTMX. It integrates Stripe for secure payment processing, and uses Celery with Redis to manage asynchronous tasks like order confirmation emails. The entire application is containerized with Docker and deployed behind Nginx for scalable and reliable hosting.

## Technology used

- Django
- HTMX
- Bootstrap
- MySQL
- Celery
- Stripe API

## To set up this project

1. cd into project directory
2. Create a new .env file by copying the env.example file
3. Open the .env file and update it with your credentials as needed
4. Build docker image with `docker-compose build`
5. Start container with `docker-compose up`
6. Project should be live at localhost port 8000.
