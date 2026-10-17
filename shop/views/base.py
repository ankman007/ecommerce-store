from shop.models import Product
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.contrib import messages
from shop.forms import ContactForm
from django.http import HttpResponse
from shop.tasks import send_contact_email
from shop.views.listing import render_product_listing


def home(request):
    return render_product_listing(request, Product.objects.all())


def contact(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            subject = f"New contact us message from {form.cleaned_data['name']}"
            if form.cleaned_data.get('subject'):
                subject += f": {form.cleaned_data['subject']}"
            message = form.cleaned_data['message']
            sender_email = form.cleaned_data['email']

            send_contact_email.delay(sender_email, subject, message)

            toast_message = (
                "Your message has been sent successfully! <a href='/contact/' class='underline'>Send another?</a>"
            )
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
