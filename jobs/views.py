from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import JobForm, RoundForm
from .models import InterviewRound, Job


class JobListView(LoginRequiredMixin, ListView):
    model = Job
    template_name = 'jobs/job_list.html'
    context_object_name = 'jobs'
    paginate_by = 25

    def paginate_queryset(self, queryset, page_size):
        """Clamp out-of-range pages instead of 404ing."""
        from django.core.paginator import EmptyPage, PageNotAnInteger
        try:
            return super().paginate_queryset(queryset, page_size)
        except (PageNotAnInteger, EmptyPage):
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
        context['show_inactive'] = self.request.GET.get('inactive') == '1'
        return context


class JobCreateView(LoginRequiredMixin, CreateView):
    model = Job
    form_class = JobForm
    template_name = 'jobs/job_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Job "{form.instance.title}" created.')
        return super().form_valid(form)


class JobEditView(LoginRequiredMixin, UpdateView):
    model = Job
    form_class = JobForm
    template_name = 'jobs/job_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, f'Job "{form.instance.title}" updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = True
        return context


class JobCloseView(LoginRequiredMixin, View):
    """Close a job: stop accepting new CV uploads. Existing candidates are untouched."""

    def post(self, request, pk):
        job = get_object_or_404(Job, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can close jobs.')
            return redirect('jobs:list')

        if job.is_active:
            job.is_active = False
            job.closed_at = timezone.now()
            job.save()
            messages.success(
                request,
                f'Job "{job.title}" closed. Existing candidates are unchanged.',
            )
        else:
            messages.info(request, f'Job "{job.title}" is already closed.')
        return redirect('jobs:detail', pk=job.pk)


class JobReopenView(LoginRequiredMixin, View):
    """Reopen a closed job: accepts CVs again and clears the closure stamp."""

    def post(self, request, pk):
        job = get_object_or_404(Job, pk=pk)
        if not request.user.is_hr():
            messages.error(request, 'Only HR can reopen jobs.')
            return redirect('jobs:list')

        if not job.is_active:
            job.is_active = True
            job.closed_at = None
            job.save()
            messages.success(request, f'Job "{job.title}" reopened and accepting CVs.')
        else:
            messages.info(request, f'Job "{job.title}" is already active.')
        return redirect('jobs:detail', pk=job.pk)



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
        context['requirements_list'] = [
            s.strip() for s in self.object.requirements.split(',') if s.strip()
        ]
        return context


class RoundCreateView(LoginRequiredMixin, CreateView):
    """Add an interview round to a job (HR only)."""
    model = InterviewRound
    form_class = RoundForm
    template_name = 'jobs/round_form.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        job = get_object_or_404(Job, pk=self.kwargs['job_pk'])
        if not job.is_active:
            messages.error(request, 'This job is closed; its rounds cannot be changed.')
            return redirect('jobs:detail', pk=job.pk)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.job_id = self.kwargs['job_pk']
        messages.success(self.request, f'Round "{form.instance.name}" added.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['job'] = get_object_or_404(Job, pk=self.kwargs['job_pk'])
        return context

    def get_success_url(self):
        return reverse('jobs:detail', kwargs={'pk': self.object.job_id})


class RoundDeleteView(LoginRequiredMixin, DeleteView):
    """Remove an interview round from a job (HR only)."""
    model = InterviewRound

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_hr():
            return redirect('jobs:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        name = self.object.name
        response = super().form_valid(form)
        messages.success(self.request, f'Round "{name}" removed.')
        return response

    def get_success_url(self):
        return reverse('jobs:detail', kwargs={'pk': self.object.job_id})
