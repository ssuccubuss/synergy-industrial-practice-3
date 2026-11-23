"""Maximum-cardinality, minimum-cost assignment on a capacitated bipartite graph."""
from collections import deque
from dataclasses import dataclass


@dataclass
class Edge:
    target: int
    reverse: int
    capacity: int
    cost: int


def assign(students, places, preferences, interested):
    """Return {student_id: (place_id, rank)}; use eligible preferences only."""
    source = 0
    sink = len(students) + len(places) + 1
    graph = [[] for _ in range(sink + 1)]
    student_nodes = {item["id"]: i for i, item in enumerate(students, 1)}
    place_nodes = {
        item["id"]: i for i, item in enumerate(places, len(students) + 1)
    }
    student_profiles = {item["id"]: item["profile"] for item in students}
    place_profiles = {item["id"]: item["profile"] for item in places}

    def edge(start, end, capacity, cost=0):
        forward = Edge(end, len(graph[end]), capacity, cost)
        reverse = Edge(start, len(graph[start]), 0, -cost)
        graph[start].append(forward)
        graph[end].append(reverse)
        return forward

    for node in student_nodes.values():
        edge(source, node, 1)
    for item in places:
        edge(place_nodes[item["id"]], sink, item["capacity"])

    candidates = []
    for item in preferences:
        student, place, rank = item["student_id"], item["place_id"], item["rank"]
        if student not in student_nodes or place not in place_nodes:
            continue
        if student_profiles[student] != place_profiles[place]:
            continue
        cost = rank * (len(students) + 1) + int((student, place) not in interested)
        forward = edge(student_nodes[student], place_nodes[place], 1, cost)
        candidates.append((student, place, rank, forward))

    while True:
        distances = [float("inf")] * len(graph)
        previous = [None] * len(graph)
        distances[source] = 0
        queue = deque([source])
        queued = {source}
        while queue:
            node = queue.popleft()
            queued.remove(node)
            for i, item in enumerate(graph[node]):
                cost = distances[node] + item.cost
                if not item.capacity or cost >= distances[item.target]:
                    continue
                distances[item.target] = cost
                previous[item.target] = (node, i)
                if item.target not in queued:
                    queue.append(item.target)
                    queued.add(item.target)
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            start, i = previous[node]
            path_edge = graph[start][i]
            path_edge.capacity -= 1
            graph[node][path_edge.reverse].capacity += 1
            node = start

    return {
        student: (place, rank)
        for student, place, rank, forward in candidates if not forward.capacity
    }

