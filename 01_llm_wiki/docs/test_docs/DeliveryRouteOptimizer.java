import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;

public class DeliveryRouteOptimizer {
    record Edge(String to, int minutes) {}
    record State(String node, int cost) {}

    static Map<String, Integer> shortestTimes(Map<String, List<Edge>> graph, String start) {
        Map<String, Integer> distance = new HashMap<>();
        PriorityQueue<State> queue = new PriorityQueue<>((a, b) -> Integer.compare(a.cost(), b.cost()));
        distance.put(start, 0);
        queue.add(new State(start, 0));
        while (!queue.isEmpty()) {
            State current = queue.poll();
            if (current.cost() != distance.get(current.node())) {
                continue;
            }
            for (Edge edge : graph.getOrDefault(current.node(), List.of())) {
                int nextCost = current.cost() + edge.minutes();
                if (nextCost < distance.getOrDefault(edge.to(), Integer.MAX_VALUE)) {
                    distance.put(edge.to(), nextCost);
                    queue.add(new State(edge.to(), nextCost));
                }
            }
        }
        return distance;
    }

    static void connect(Map<String, List<Edge>> graph, String from, String to, int minutes) {
        graph.computeIfAbsent(from, ignored -> new ArrayList<>()).add(new Edge(to, minutes));
        graph.computeIfAbsent(to, ignored -> new ArrayList<>()).add(new Edge(from, minutes));
    }

    public static void main(String[] args) {
        Map<String, List<Edge>> graph = new HashMap<>();
        connect(graph, "HUB", "A01", 12);
        connect(graph, "HUB", "B02", 18);
        connect(graph, "A01", "C03", 7);
        connect(graph, "B02", "C03", 4);
        connect(graph, "B02", "D04", 11);
        connect(graph, "C03", "E05", 10);
        connect(graph, "D04", "E05", 3);

        Map<String, Integer> serviceMinutes = Map.of("A01", 4, "B02", 6, "C03", 5, "D04", 7, "E05", 8);
        Map<String, Integer> travel = shortestTimes(graph, "HUB");
        List<String> stops = new ArrayList<>(serviceMinutes.keySet());
        stops.sort((a, b) -> {
            int compare = Integer.compare(travel.get(a) + serviceMinutes.get(a), travel.get(b) + serviceMinutes.get(b));
            return compare != 0 ? compare : a.compareTo(b);
        });
        for (String stop : stops) {
            int eta = travel.get(stop) + serviceMinutes.get(stop);
            System.out.println(stop + "|" + travel.get(stop) + "|" + eta);
        }
    }
}
