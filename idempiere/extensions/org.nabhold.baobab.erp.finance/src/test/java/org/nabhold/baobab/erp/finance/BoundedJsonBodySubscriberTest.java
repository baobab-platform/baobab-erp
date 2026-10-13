package org.nabhold.baobab.erp.finance;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Flow;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BoundedJsonBodySubscriberTest {
    static final class TestSubscription implements Flow.Subscription {
        boolean cancelled;
        long requested;
        @Override public void request(long count) { requested += count; }
        @Override public void cancel() { cancelled = true; }
    }
    @Test void completeBodyOnlyAndExactByteBoundary() throws Exception {
        var subscriber = new BoundedJsonBodySubscriber();
        var flow = new TestSubscription();
        subscriber.onSubscribe(flow);
        subscriber.onNext(List.of(ByteBuffer.wrap(new byte[1000]), ByteBuffer.wrap(new byte[15384])));
        assertFalse(subscriber.getBody().toCompletableFuture().isDone());
        assertFalse(flow.cancelled);
        subscriber.onComplete();
        assertEquals(16384, subscriber.getBody().toCompletableFuture().get().length);
        assertEquals(2, flow.requested);
    }
    @Test void oversizedSingleOrCumulativeChunksCancelBeforeRetention() {
        for (boolean cumulative : new boolean[]{false, true}) {
            var subscriber = new BoundedJsonBodySubscriber();
            var flow = new TestSubscription();
            subscriber.onSubscribe(flow);
            if (cumulative) subscriber.onNext(List.of(ByteBuffer.wrap(new byte[1000])));
            subscriber.onNext(List.of(ByteBuffer.wrap(new byte[cumulative ? 15385 : 16385])));
            assertTrue(flow.cancelled);
            assertThrows(ExecutionException.class, () -> subscriber.getBody().toCompletableFuture().get());
            subscriber.onComplete();
            assertTrue(subscriber.getBody().toCompletableFuture().isCompletedExceptionally());
        }
    }
    @Test void publisherFailureCannotSupplyPartialFact() {
        var subscriber = new BoundedJsonBodySubscriber();
        var flow = new TestSubscription();
        subscriber.onSubscribe(flow);
        subscriber.onNext(List.of(ByteBuffer.wrap(new byte[1])));
        subscriber.onError(new IllegalStateException("synthetic disconnect"));
        subscriber.onComplete();
        assertThrows(ExecutionException.class, () -> subscriber.getBody().toCompletableFuture().get());
    }
}
