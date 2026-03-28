from shop.models import Product, Category
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.contrib import messages
from django.db.models import Count
from shop.forms import ContactForm
from django.http import HttpResponse
from shop.utils import check_product_for_cart
from shop.tasks import send_contact_email

def home(request):
    products = Product.objects.all()
    categories = Category.objects.annotate(product_count=Count('products'))
    cart_product_ids = check_product_for_cart(request)

    context = {
        'products': products,
        'categories': categories,
        'cart_product_ids': cart_product_ids,  
    }
    return render(request, 'a_shop/home.html', context)


def contact(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            
            subject = f"New contact us message from {form.cleaned_data['name']}"
            message = form.cleaned_data['message']
            sender_email = form.cleaned_data['email']

            send_contact_email.delay(sender_email, subject, message)

            toast_message = "Your message has been sent successfully! <a href='/contact/' class='underline'>Send another?</a>"
            toast_html = render_to_string("a_shop/partials/toast.html", {"message": toast_message})
            messages.success(request, toast_html)
            return redirect('home')
    else:
        form = ContactForm()

    return render(request, 'a_shop/contact.html', {'form': form})


def contact_success(request):
    return HttpResponse("Thanks for contacting us!")


def about(request):
    return render(request, 'a_shop/about-us.html')


def privacy_policy(request):
    return render(request, 'a_shop/privacy-policy.html')
