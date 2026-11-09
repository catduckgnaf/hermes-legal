# Playbook: Employment Agreement
id: employment
name: Employment Agreement
version: 1
description: Approved positions for reviewing an employment agreement. Edit this file to change review behavior; no code change is needed.

This playbook is a sample. Employment law varies by jurisdiction, and a firm should replace the positions with its own and check current law before relying on a review.

## Rules

### require-at-will-statement
title: At-will employment statement is required
kind: required
severity: high
topic: at-will employment
patterns: at-will; at will employment
rationale: Where the approved position is at-will employment, the agreement must say so plainly and state that either party may end the relationship.
fallback: Employment is at will. Either party may terminate the employment relationship at any time, with or without cause, subject to applicable law.

### require-compensation
title: Compensation terms are required
kind: required
severity: medium
topic: compensation
patterns: compensation; salary; base pay
rationale: The agreement must state compensation so there is no dispute about the core bargain.
fallback: The employee will be paid the salary stated in the offer schedule, payable on the employer's regular payroll dates.

### forbid-overbroad-noncompete-language
title: Overbroad non-compete language is forbidden
kind: forbidden
severity: high
topic: non-compete
patterns: shall not work for any competitor; anywhere in the world; worldwide non-compete
rationale: A worldwide ban on working for any competitor is outside the approved position and may be unenforceable in some jurisdictions.
fallback: For twelve months after employment ends, the employee will not perform the same duties for a direct competitor within the region where the employee worked, to the extent permitted by applicable law.

### noncompete-duration-position
title: Non-compete duration position
kind: fallback
severity: high
topic: non-compete
patterns: non-compete; noncompete; shall not compete
preferred: six months; 6 months; six (6) months
acceptable: twelve months; 12 months; twelve (12) months
rationale: Six months is preferred. Twelve months is an acceptable fallback position. A longer period is a deviation.
fallback: Any non-compete lasts no longer than twelve months after employment ends and is limited to the region and duties permitted by applicable law.

### require-confidentiality-employment
title: Confidentiality duty is required
kind: required
severity: medium
topic: confidentiality
patterns: confidential information; confidentiality
rationale: An employment agreement should state the duty to protect confidential information.
fallback: The employee will protect confidential information during and after employment and will use it only for the employer's business.

## Clause library

### at-will-statement
title: At-will employment
language: Employment is at will. Either party may terminate the employment relationship at any time, with or without cause, subject to applicable law.
fallback: If a fixed term is required for the role, state the term and the termination rights inside that term explicitly instead of using at-will language.
notes: Some jurisdictions limit at-will language; a human must check the governing jurisdiction.

### noncompete-narrow
title: Narrow non-compete
language: For twelve months after employment ends, the employee will not perform the same duties for a direct competitor within the region where the employee worked, to the extent permitted by applicable law.
fallback: If any non-compete is refused or barred, use confidentiality and non-solicitation language alone.
notes: The fallback in the library is the outer limit, not the opening position; six months is preferred in the rule above.

### confidentiality-employment
title: Confidentiality in employment
language: The employee will protect confidential information during and after employment and will use it only for the employer's business.
fallback: Accept a duty limited to information marked confidential plus trade secrets if the preferred language will not be accepted.
notes: Trade secret protection should not depend on marking alone.
