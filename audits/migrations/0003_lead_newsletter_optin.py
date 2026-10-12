from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audits", "0002_lead"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="newsletter_optin",
            field=models.BooleanField(default=False, help_text="Ticked the separate box. Only these people may get newsletters.", verbose_name="Said yes to tips emails"),
        ),
        migrations.AddField(
            model_name="lead",
            name="newsletter_optin_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Tips opt-in date"),
        ),
    ]
