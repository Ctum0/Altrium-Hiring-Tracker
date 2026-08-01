from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView

from .forms import JobForm, RoundForm
from .models import InterviewRound, Job


class JobListView(LoginRequiredMixin, ListView):
    model = Job
    template_name = 'jobs/job_list.html'
    context_object_name = 'jobs'
    paginate_by = 25

    def paginate_queryset(self, queryset, page_size):
        """Clamp out-of-range pages instead of 404ing."""
        try:
            return super().paginate_queryset(queryset, page_size)
        except Exception:
            self.kwargs['page'] = 'last'
            return super().paginate_queryset(queryset, page_size)

    def get_queryset(self):
        qs = (
            Job.objects.select_related('hiring_manager', 'created_by')
            .annotate(num_applications=Count('applications'))
            .order_by('-created_at')
        )
        if self.request.GET.get('inactive') != '1':
            qs = qs.filter(is_active=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'jobs'
        return context


class JobCreateView(LoginRequiredMixin, CreateView):
    model = Job
    form_class = JobForm
    template_name = 'jobs/job_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Job "{form.instance.title}" created.')
        return super().form_valid(form)


class JobDetailView(LoginRequiredMixin, DetailView):
    model = Job
    template_name = 'jobs/job_detail.html'
    context_object_name = 'job'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_nav'] = 'jobs'
        context['rounds'] = self.object.rounds.all()
        context['round_form'] = RoundForm()
        context['can_edit'] = self.request.user.is_hr()
        return context


class RoundCreateView(LoginRequiredMixin, CreateView):
    """Add an interview round to a job (HR only)."""
    model = InterviewRound
    form_class = RoundForm
    template_name = 'jobs/round_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.job_id = self.kwargs['job_pk']
        messages.success(self.request, f'Round "{form.instance.name}" added.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['job'] = Job.objects.get(pk=self.kwargs['job_pk'])
        return context

    def get_success_url(self):
        return reverse('jobs:detail', kwargs={'pk': self.object.job_id})


class RoundDeleteView(LoginRequiredMixin, DeleteView):
    """Remove an interview round from a job (HR only)."""
    model = InterviewRound

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('jobs:detail', kwargs={'pk': self.object.job_id})
