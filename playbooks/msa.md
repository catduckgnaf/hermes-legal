# Playbook: Master Services Agreement
id: msa
name: Master Services Agreement
version: 1
description: Approved positions for reviewing a master services agreement. Edit this file to change review behavior; no code change is needed.

This playbook is a sample. A firm should replace the positions with its own before relying on a review.

## Rules

### require-limitation-of-liability
title: Limitation of liability is required
kind: required
severity: high
topic: liability
patterns: limitation of liability; liability shall not exceed; aggregate liability
rationale: A services agreement without a liability cap leaves exposure unbounded.
fallback: Neither party's aggregate liability arising under this Agreement exceeds the amounts paid or payable in the twelve months before the claim.

### require-payment-terms
title: Payment terms are required
kind: required
severity: medium
topic: payment
patterns: payment; fees
must_contain: invoice
rationale: Payment terms must state how and when invoices are paid.
fallback: Undisputed invoices are payable Net 30 after receipt of a correct invoice.

### payment-window-position
title: Payment window position
kind: fallback
severity: medium
topic: payment
patterns: Net 60; Net 45; Net 30; payable within
preferred: Net 30
acceptable: Net 45
rationale: Net 30 is preferred. Net 45 is an acceptable fallback position. Net 60 is a deviation.
fallback: Undisputed invoices are payable Net 30 after receipt of a correct invoice.

### require-ip-ownership
title: Intellectual property ownership is required
kind: required
severity: high
topic: intellectual property
patterns: intellectual property; ownership of deliverables; work product
rationale: The agreement must say who owns deliverables and work product.
fallback: On full payment, deliverables created for the client are assigned to the client, while the provider retains its pre-existing intellectual property and tools.

### forbid-unlimited-liability
title: Unlimited liability is forbidden
kind: forbidden
severity: high
topic: liability
patterns: unlimited liability; liability shall be unlimited
rationale: Unlimited liability is outside the approved position.
fallback: Neither party's aggregate liability arising under this Agreement exceeds the amounts paid or payable in the twelve months before the claim.

### governing-law-position-msa
title: Governing law position
kind: fallback
severity: medium
topic: governing law
patterns: governing law; governed by
preferred: Delaware
acceptable: New York; California
rationale: Delaware is preferred. New York or California are acceptable fallback positions.
fallback: This Agreement is governed by the laws of the State of Delaware, without regard to its conflict of laws principles.

## Clause library

### limitation-of-liability
title: Limitation of liability
language: Neither party's aggregate liability arising under this Agreement exceeds the amounts paid or payable in the twelve months before the claim.
fallback: If a twelve-month cap will not be accepted, accept a cap of twenty-four months of amounts paid or payable.
notes: Carve-outs for willful misconduct or breach of confidentiality should be stated separately if the firm approves them.

### payment-terms
title: Payment terms
language: Undisputed invoices are payable Net 30 after receipt of a correct invoice.
fallback: Accept Net 45 as a fallback position without escalation.
notes: Net 60 or longer is a deviation that needs a human decision.

### ip-ownership
title: Intellectual property ownership
language: On full payment, deliverables created for the client are assigned to the client, while the provider retains its pre-existing intellectual property and tools.
fallback: If assignment will not be accepted, accept a broad, perpetual license to deliverables on full payment.
notes: The fallback is a license, not ownership, and should be flagged in the review.
