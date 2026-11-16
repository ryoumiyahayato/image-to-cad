"""Carry explicit local confirmations as review candidates across CAD saves.

References point to immutable historical states, never establish current identity.
"""
from collections import defaultdict
from copy import deepcopy

EXPLICIT = "EXPLICIT_CURRENT_MEMBER_SOURCE_TEXT_REPAIR"
PENDING = "PRIOR_CONFIRMATION_REVIEW_REQUIRED"
EQUAL = {"CONTENT_EQUAL", "FUNCTIONALLY_EQUAL", "EQUAL_MULTIPLICITY_ONLY"}


def resolve_confirmation(project, reference):
    try:
        relation = project.state["states"][reference["state"]]["relations"][reference["member"]]
        if relation["status"] != EXPLICIT or not relation["source_evidence"] or not relation["confirmation"]:
            raise ValueError("Not an explicit historical confirmation")
        return deepcopy(relation)
    except (KeyError, TypeError) as exc:
        raise ValueError("UNRESOLVED_CONFIRMATION_REFERENCE") from exc


def project_relations(project, base, rows, report):
    previous_state = project.state["states"][base]
    previous = previous_state["relations"]
    mappings = {r["after"]: r for r in report["mappings"]}
    relations = {}
    for row in rows:
        handle = row["handle"]
        match = mappings.get(handle)
        if match:
            old = previous.get(match["before"], {})
            relations[handle] = {"status": "CONTENT_EQUIVALENT_IDENTITY_UNPROVEN" if match["status"] in EQUAL else "USER_MODIFIED_SOURCE_CANDIDATE", "prior_member_candidate": match["before"], "historical_source": old.get("historical_source", {}), "current_geometry_is_source_observation": False, "source_automatic_operations": False}
        else:
            relations[handle] = {"status": "USER_ADDED_OR_UNRESOLVED", "historical_source": {}, "current_geometry_is_source_observation": False, "source_automatic_operations": False}

    # Equality groups are many-candidate associations. Do not take the
    # comparator's arbitrary equal-multiplicity pairing as instance identity.
    edges = defaultdict(lambda: defaultdict(set))
    for match in report["mappings"]:
        edges[match["before"]][match["after"]].add(match["status"])
    for group in report["duplicate_groups"]:
        for before in group["before"]:
            for after in group["after"]:
                edges[before][after].add("EQUAL_MULTIPLICITY_ONLY")
    for group in report["ambiguous"]:
        for after in group["after_candidates"]:
            edges[group["before"]][after].add("AMBIGUOUS")

    facts = {}
    for member, relation in previous.items():
        explicit = relation.get("status") == EXPLICIT
        refs = [{"state": base, "member": member}] if explicit else relation.get("prior_confirmations", [])
        for reference in refs:
            proof = resolve_confirmation(project, reference)
            key = (reference["state"], reference["member"])
            item = facts.setdefault(key, {"reference": reference, "proof": proof, "members": set(), "explicit": False})
            item["members"].add(member)
            item["explicit"] |= explicit

    unresolved = deepcopy(previous_state.get("unresolved_relation_refs", []))
    changes = []
    for key in sorted(facts):
        fact = facts[key]
        members = sorted(fact["members"])
        afters = sorted({h for before in members for h in edges[before]})
        comparison = {status for before in members for statuses in edges[before].values() for status in statuses}
        reference = fact["reference"]
        for handle in afters:
            relation = relations[handle]
            relation["status"] = PENDING
            relation.setdefault("prior_confirmations", []).append(deepcopy(reference))
            relation["historical_current_member_identity"] = "NOT_PROVEN"
            relation["review_required"] = True
        if not afters:
            unresolved.append({"reference": deepcopy(reference), "reason": "NO_CURRENT_CANDIDATE", "last_members": members})
        # Already pending, same multiplicity and equal content: keep the
        # review information visible, but do not prompt for the same issue again.
        changed = fact["explicit"] or len(afters) != len(members) or not comparison <= EQUAL or any(not edges[h] for h in members)
        if changed:
            changes.append({
                "reference": deepcopy(reference), "before_members": members,
                "after_candidates": afters, "before_status": EXPLICIT if fact["explicit"] else PENDING,
                "after_status": PENDING if afters else "NO_CURRENT_CANDIDATE",
                "reason": "EXTERNAL_SAVE_REQUIRES_RELATION_REVIEW" if fact["explicit"] else "PENDING_CANDIDATE_SET_OR_CONTENT_CHANGED",
                "source_uuid": fact["proof"]["source_evidence"].get("source_uuid"),
                "prior_actor": fact["proof"]["confirmation"].get("actor"),
                "historical_identity": "NOT_PROVEN", "source_automatic_operations": False,
            })
    return relations, unresolved, changes
