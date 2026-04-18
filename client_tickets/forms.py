from django import forms
from django.contrib.auth.models import User

from task_app.models import Department

from .models import ClientTicket, ClientTicketType
from .utils import validate_attachment_batch


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        if not isinstance(data, (list, tuple)):
            data = [data]
        return [super(MultipleFileField, self).clean(item, initial) for item in data]


class ClientTicketForm(forms.ModelForm):
    attachments = MultipleFileField(required=False)

    class Meta:
        model = ClientTicket
        fields = [
            "title",
            "description",
            "ticket_type",
            "ticket_type_other",
            "requester_name",
            "requester_email",
            "requester_number",
            "assigned_to",
            "project_manager",
            "user_type",
            "source_system",
            "priority",
            "department",
            "status",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "status": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        active_users = User.objects.filter(is_active=True).order_by("first_name", "username")
        self.fields["assigned_to"].queryset = active_users
        self.fields["project_manager"].queryset = active_users
        self.fields["assigned_to"].required = True
        self.fields["project_manager"].required = False
        self.fields["ticket_type"].queryset = ClientTicketType.objects.filter(is_active=True).select_related("department")
        self.fields["department"].queryset = Department.objects.all().order_by("name")
        self.fields["ticket_type"].required = False
        self.fields["status"].required = False
        self.fields["ticket_type_other"].required = False
        self.fields["attachments"].help_text = (
            "Up to 5 files total. Allowed formats: jpg, jpeg, png, pdf, mp4, heic, hevc. Max 10 MB each."
        )
        self.fields["source_system"].initial = ClientTicket.SOURCE_MANUAL
        self.fields["priority"].initial = ClientTicket.PRIORITY_MEDIUM
        self.fields["user_type"].initial = ClientTicket.USER_TYPE_INTERNAL

    def clean(self):
        cleaned_data = super().clean()
        ticket_type = cleaned_data.get("ticket_type")
        ticket_type_other = (cleaned_data.get("ticket_type_other") or "").strip()
        department = cleaned_data.get("department")

        if not ticket_type and not ticket_type_other:
            raise forms.ValidationError("Select a ticket type or provide a custom ticket type.")

        if ticket_type and ticket_type.department and not department:
            cleaned_data["department"] = ticket_type.department
            department = ticket_type.department

        if not department:
            raise forms.ValidationError("Department is required.")

        return cleaned_data

    def clean_attachments(self):
        attachments = self.files.getlist("attachments")
        existing_count = self.instance.attachments.count() if self.instance.pk else 0
        return validate_attachment_batch(attachments, existing_count=existing_count)


class ClientTicketUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=ClientTicket.STATUS_CHOICES, required=False)
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), required=False)
    attachments = MultipleFileField(required=False)

    def __init__(self, *args, **kwargs):
        self.ticket = kwargs.pop("ticket")
        super().__init__(*args, **kwargs)

    def clean_attachments(self):
        attachments = self.files.getlist("attachments")
        return validate_attachment_batch(attachments, existing_count=self.ticket.attachments.count())


class ClientTicketInditechUpdateForm(ClientTicketUpdateForm):
    pass


class ClientTicketClientUpdateForm(ClientTicketUpdateForm):
    pass
