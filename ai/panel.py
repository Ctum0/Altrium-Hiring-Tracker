"""
AI Panel Consensus & Conflict Resolution Engine.
Synthesizes multi-interviewer feedback across progressive interview rounds,
calculates round-weighted consensus scores, tallies votes, and resolves conflicting panel notes.
"""

def synthesize_panel_consensus(application):
    """
    Computes a multi-interviewer consensus analysis for a JobApplication.
    Returns a dictionary with vote tallies, weighted score, divergence status,
    agreed strengths, conflicting areas, and AI recommended resolution.
    """
    feedbacks = list(
        application.feedbacks.select_related('interviewer', 'round').order_by('submitted_at')
    )
    if not feedbacks:
        return None

    # Calculate progressive round weighting
    total_weighted_score = 0.0
    total_weight = 0.0
    scores_list = []

    hire_votes = 0
    hold_votes = 0
    reject_votes = 0

    evaluators = []

    for fb in feedbacks:
        raw_score = float(fb.score or 0)
        # Normalize score to 10-point scale if entered out of 100
        score_10 = raw_score / 10.0 if raw_score > 10 else raw_score
        scores_list.append(score_10)

        # Progressive round weight: Round 1 (1.0), Round 2 (1.5), Round 3+ (2.0)
        round_order = getattr(fb.round, 'order', 1) if fb.round else 1
        if round_order <= 1:
            weight = 1.0
        elif round_order == 2:
            weight = 1.5
        else:
            weight = 2.0

        total_weighted_score += score_10 * weight
        total_weight += weight

        # Vote classification
        if score_10 >= 7.0:
            vote = 'Hire'
            hire_votes += 1
        elif score_10 >= 5.0:
            vote = 'Hold'
            hold_votes += 1
        else:
            vote = 'Reject'
            reject_votes += 1

        evaluators.append({
            'name': fb.interviewer.get_full_name() or fb.interviewer.username,
            'role': fb.interviewer.get_role_display() if hasattr(fb.interviewer, 'get_role_display') else 'Interviewer',
            'round_name': fb.round.name if fb.round else 'Interview',
            'round_order': round_order,
            'score_10': round(score_10, 1),
            'vote': vote,
            'notes': fb.notes,
            'submitted_at': fb.submitted_at,
        })

    weighted_avg_10 = round(total_weighted_score / total_weight, 1) if total_weight > 0 else 0.0
    weighted_avg_100 = int(round(weighted_avg_10 * 10))

    # Detect conflict / divergence
    max_score = max(scores_list) if scores_list else 0
    min_score = min(scores_list) if scores_list else 0
    score_spread = round(max_score - min_score, 1)

    is_single_evaluator = len(feedbacks) == 1
    is_divergent = not is_single_evaluator and ((hire_votes > 0 and reject_votes > 0) or (score_spread >= 3.0))

    if is_single_evaluator:
        status_code = 'single_evaluator'
        status_label = f"Single Evaluator Summary ({evaluators[0]['vote']})"
        status_badge_class = 'badge-info'
        status_tone = 'blue'
    elif is_divergent:
        status_code = 'divergent'
        status_label = 'Panel Conflict / Divergent'
        status_badge_class = 'badge-danger'
        status_tone = 'red'
    elif hire_votes > 0 and reject_votes == 0:
        status_code = 'consensus_hire'
        status_label = 'Panel Consensus: Recommend Hire'
        status_badge_class = 'badge-success'
        status_tone = 'green'
    elif reject_votes > 0 and hire_votes == 0:
        status_code = 'consensus_reject'
        status_label = 'Panel Consensus: Recommend Reject'
        status_badge_class = 'badge-danger'
        status_tone = 'red'
    else:
        status_code = 'neutral'
        status_label = 'Panel Consensus: Hold / Needs Review'
        status_badge_class = 'badge-warning'
        status_tone = 'amber'

    # Synthesize text notes for strengths vs conflicts
    all_notes_text = ' '.join([e['notes'] for e in evaluators]).lower()

    agreed_strengths = []
    conflict_points = []

    # Keyword extraction heuristics
    if any(k in all_notes_text for k in ['python', 'backend', 'code', 'django', 'architecture', 'technical', 'orm']):
        agreed_strengths.append('Strong technical competence and core domain expertise.')
    if any(k in all_notes_text for k in ['communication', 'team', 'lead', 'clear', 'articulate']):
        agreed_strengths.append('Articulate candidate with clear communication skills.')
    if any(k in all_notes_text for k in ['experience', 'senior', 'solid', 'problem', 'frontend', 'devops']):
        agreed_strengths.append('Proven industry experience and domain problem-solving capability.')
    if not agreed_strengths:
        agreed_strengths.append('Candidate demonstrates baseline technical proficiency for the role.')

    if is_single_evaluator:
        conflict_points.append(
            f"Evaluated by {evaluators[0]['name']} ({evaluators[0]['round_name']}) with score {evaluators[0]['score_10']}/10. Awaiting secondary panel evaluation for multi-evaluator consensus."
        )
    elif is_divergent:
        for ev in evaluators:
            if ev['vote'] == 'Hire':
                conflict_points.append(
                    f"{ev['name']} ({ev['round_name']}, Score: {ev['score_10']}/10) recommended HIRE based on technical strengths."
                )
            elif ev['vote'] == 'Reject':
                conflict_points.append(
                    f"{ev['name']} ({ev['round_name']}, Score: {ev['score_10']}/10) recommended REJECT due to evaluation concerns."
                )
            else:
                conflict_points.append(
                    f"{ev['name']} ({ev['round_name']}, Score: {ev['score_10']}/10) voted HOLD / NEUTRAL."
                )
    else:
        conflict_points.append('No major conflicting notes detected across interview rounds.')

    # Formulate actionable HR recommendation
    if is_single_evaluator:
        recommendation = (
            f"Single evaluation submitted by {evaluators[0]['name']} ({evaluators[0]['score_10']}/10). "
            f"HR Recommendation: Assign a secondary panel interviewer to establish multi-evaluator consensus."
        )
    elif is_divergent:
        recommendation = (
            f"Panel divergence detected ({hire_votes} Hire vs. {reject_votes} Reject across {len(feedbacks)} evaluations). "
            f"Progressive round-weighted average is {weighted_avg_10}/10 ({weighted_avg_100}%). "
            f"HR Recommendation: Schedule a 20-min panel alignment sync or a targeted tie-breaker interview before making a final offer decision."
        )
    elif status_code == 'consensus_hire':
        recommendation = (
            f"Unanimous panel alignment across {len(feedbacks)} round(s). "
            f"Weighted panel average: {weighted_avg_10}/10 ({weighted_avg_100}%). "
            f"HR Recommendation: Proceed to Offer preparation."
        )
    elif status_code == 'consensus_reject':
        recommendation = (
            f"Unanimous panel rejection across {len(feedbacks)} round(s). "
            f"Weighted panel average: {weighted_avg_10}/10. "
            f"HR Recommendation: Send respectful rejection communication."
        )
    else:
        recommendation = (
            f"Panel feedback is neutral/mixed ({weighted_avg_10}/10). "
            f"HR Recommendation: Re-evaluate candidate against current role priorities or keep on hold."
        )

    return {
        'total_evaluators': len(evaluators),
        'evaluators': evaluators,
        'weighted_avg_10': weighted_avg_10,
        'weighted_avg_100': weighted_avg_100,
        'hire_votes': hire_votes,
        'hold_votes': hold_votes,
        'reject_votes': reject_votes,
        'is_single_evaluator': is_single_evaluator,
        'is_divergent': is_divergent,
        'score_spread': score_spread,
        'status_code': status_code,
        'status_label': status_label,
        'status_badge_class': status_badge_class,
        'status_tone': status_tone,
        'agreed_strengths': agreed_strengths,
        'conflict_points': conflict_points,
        'recommendation': recommendation,
    }
