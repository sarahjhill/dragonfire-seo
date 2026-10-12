from django import forms


class TorchForm(forms.Form):
    target = forms.CharField(
        label="Website (or folder)",
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "sarahjhill.com", "autofocus": True}),
    )
    brand = forms.CharField(label="Business name", max_length=200, required=False,
                            widget=forms.TextInput(attrs={"placeholder": "Sarah J Hill"}))
    service = forms.CharField(label="What they do", max_length=200, required=False,
                              widget=forms.TextInput(attrs={"placeholder": "web designer for tradeswomen"}))
    towns = forms.CharField(label="Towns they serve", max_length=300, required=False,
                            widget=forms.TextInput(attrs={"placeholder": "Cardiff, Birmingham"}))
    max_pages = forms.IntegerField(label="Max pages", min_value=1, max_value=200, initial=40)
    ai = forms.BooleanField(label="Ask the AIs if they recommend this business", required=False, initial=True)


class FreeCheckForm(forms.Form):
    """The public lead-magnet form. Kept short on purpose: every extra box loses people."""

    website = forms.CharField(label="Your website", max_length=300,
                              widget=forms.TextInput(attrs={"placeholder": "yourbusiness.co.uk", "autofocus": True,
                                                            "inputmode": "url", "autocomplete": "url"}))
    name = forms.CharField(label="Your first name", max_length=120,
                           widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    email = forms.EmailField(label="Your email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    business = forms.CharField(label="Business or charity name", max_length=200, required=False)
    service = forms.CharField(label="What you do", max_length=200, required=False,
                              widget=forms.TextInput(attrs={"placeholder": "e.g. electrician, bakery, community choir"}))
    town = forms.CharField(label="Where you work", max_length=120, required=False,
                           widget=forms.TextInput(attrs={"placeholder": "e.g. Cardiff"}))
    consent = forms.BooleanField(
        label="Send me my full report and let Sarah get in touch about it. No spam.",
        required=True)
    # Separate, optional, unticked: the ONLY way someone joins the tips/newsletter list (UK GDPR / PECR).
    tips = forms.BooleanField(
        label="Yes, also send me occasional tips on getting taken seriously online. Unsubscribe any time.",
        required=False)
    # Honeypot: real people never see or fill this in. Bots do.
    company_url = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
