# Playbook: Mutual NDA
id: nda
name: Mutual NDA
version: 1
description: Approved positions for reviewing a mutual non-disclosure agreement. Edit this file to change review behavior; no code change is needed.

This playbook is a sample. A firm should replace the positions with its own before relying on a review.

## Rules

### require-confidentiality-definition
title: Definition of Confidential Information is required
kind: required
severity: high
topic: confidentiality
patterns: confidential information
must_contain: written; oral
rationale: Without a definition that covers written and oral disclosures, the duty has no clear scope.
fallback: Confidential Information means non-public information disclosed in written, oral, or electronic form that is marked confidential or that should reasonably be understood to be confidential.

### require-return-of-materials
title: Return or destruction of materials is required
kind: required
severity: medium
topic: return of materials
patterns: return or destroy; return of materials; destroy all copies
rationale: The agreement must say what happens to shared material when the relationship ends.
fallback: On request, the receiving party will return or destroy all copies of Confidential Information and confirm destruction in writing.

### forbid-perpetual-confidentiality
title: Confidentiality must not be perpetual
kind: forbidden
severity: high
topic: confidentiality
patterns: in perpetuity; perpetual confidentiality
rationale: Perpetual confidentiality is outside the approved position except for trade secrets.
fallback: The duty of confidentiality survives for three years after disclosure, except for trade secrets, which are protected for as long as they remain trade secrets.

### governing-law-position
title: Governing law position
kind: fallback
severity: medium
topic: governing law
patterns: governing law; governed by
preferred: Delaware
acceptable: New York; California
rationale: Delaware is preferred. New York or California are acceptable fallback positions.
fallback: This Agreement is governed by the laws of the State of Delaware, without regard to its conflict of laws principles.

### require-term
title: A stated term is required
kind: required
severity: medium
topic: term
patterns: term of this agreement; agreement term; expires
rationale: An NDA without a stated term leaves the parties unsure when duties end.
fallback: The term of this Agreement is two years from the effective date.

## Clause library

### confidentiality-definition
title: Definition of Confidential Information
language: Confidential Information means non-public information disclosed in written, oral, or electronic form that is marked confidential or that should reasonably be understood to be confidential.
fallback: If the counterparty will not accept the preferred language, accept a definition limited to written and electronic disclosures that are marked confidential.
notes: Preferred position covers oral disclosures; the fallback narrows the marking requirement trade-off explicitly.

### return-of-materials
title: Return or destruction of materials
language: On request, the receiving party will return or destroy all copies of Confidential Information and confirm destruction in writing.
fallback: If return is not practical, accept certified destruction alone.
notes: Certification should come from an officer or an authorized representative.

### governing-law-nda
title: Governing law
language: This Agreement is governed by the laws of the State of Delaware, without regard to its conflict of laws principles.
fallback: Accept New York or California governing law without escalation.
notes: Any other governing law is a deviation that needs a human decision.
