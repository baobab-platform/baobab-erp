package org.nabhold.baobab.erp.finance;

import java.io.ByteArrayOutputStream;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Flow;

/** Accumulate at most one small CP fact, cancelling before an oversized chunk
 * is copied. Completion means the WHOLE body arrived, so the caller's bounded
 * future wait also covers a server that trickles its body after the headers. */
final class BoundedJsonBodySubscriber implements HttpResponse.BodySubscriber<byte[]> {
    private static final int LIMIT = 16384;
    private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
    private final CompletableFuture<byte[]> result = new CompletableFuture<>();
    private Flow.Subscription subscription;

    @Override public CompletionStage<byte[]> getBody() { return result; }
    @Override public void onSubscribe(Flow.Subscription incoming) {
        if (subscription != null) { incoming.cancel(); return; }
        subscription = incoming;
        subscription.request(1);
    }
    @Override public void onNext(List<ByteBuffer> buffers) {
        if (result.isDone()) return;
        long length = bytes.size();
        for (ByteBuffer buffer : buffers) length += buffer.remaining();
        if (length > LIMIT) {
            subscription.cancel();
            result.completeExceptionally(new IllegalStateException("Oversized CP wire fact"));
            return;
        }
        for (ByteBuffer buffer : buffers) {
            byte[] chunk = new byte[buffer.remaining()];
            buffer.get(chunk);
            bytes.write(chunk, 0, chunk.length);
        }
        subscription.request(1);
    }
    @Override public void onError(Throwable failed) { result.completeExceptionally(failed); }
    @Override public void onComplete() { result.complete(bytes.toByteArray()); }
}
