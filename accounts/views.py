from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView


class LoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    pass


class HomeView(TemplateView):
    template_name = 'accounts/home.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse_lazy('accounts:login'))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Role-based landing cards
        if user.is_hr():
            context['cards'] = [
                {
                    'title': 'Jobs',
                    'body': 'Create job postings and configure interview rounds.',
                    'href': 'jobs:list',
                    'cta': 'Manage jobs',
                },
                {
                    'title': 'Candidates',
                    'body': 'Upload CVs, review parsed profiles, and shortlist.',
                    'href': 'candidates:list',
                    'cta': 'Review candidates',
                },
            ]
        elif user.is_interviewer():
            context['cards'] = [
                {
                    'title': 'Assigned candidates',
                    'body': 'Candidates assigned to you appear here.',
                    'href': 'candidates:list',
                    'cta': 'View my candidates',
                },
            ]
        else:  # Management
            context['cards'] = [
                {
                    'title': 'Candidate pipeline',
                    'body': 'High-level candidate overview across all positions.',
                    'href': 'candidates:list',
                    'cta': 'View candidates',
                },
                {
                    'title': 'Jobs',
                    'body': 'Open positions and their progress.',
                    'href': 'jobs:list',
                    'cta': 'View jobs',
                },
            ]

        context['active_nav'] = 'dashboard'
        return context
