"""Sequential background worker for processing extraction jobs."""

import asyncio
import logging
import shutil
from pathlib import Path

from yoink.api.jobs import JobStore
from yoink.extractor import LayoutExtractor
from yoink.pipeline import run_pipeline

logger = logging.getLogger(__name__)


class ExtractionWorker:
    """
    Processes extraction jobs one at a time from an asyncio.Queue.
    
    This worker runs as a background task and sequentially processes PDF
    extraction jobs. It maintains a queue of job IDs and processes them
    in FIFO order, updating job status in the database as processing progresses.
    """

    def __init__(
        self,
        job_store: JobStore,
        extractor: LayoutExtractor,
        output_base_dir: str = "./job_data",
    ):
        """
        Initialize the extraction worker.
        
        Args:
            job_store: Database interface for job persistence
            extractor: The YOLO-based layout extractor instance
            output_base_dir: Directory where job outputs will be stored
        """
        self._job_store = job_store
        self._extractor = extractor
        self._output_base_dir = Path(output_base_dir)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background processing loop as an asyncio task."""
        self._task = asyncio.create_task(self._process_loop())
        logger.info("ExtractionWorker started")

    async def stop(self) -> None:
        """
        Gracefully stop the worker.
        
        Cancels the processing task and waits for it to complete.
        Any job currently being processed will be interrupted.
        """
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                # Expected when cancelling the task
                pass
            self._task = None
        logger.info("ExtractionWorker stopped")

    async def enqueue(self, job_id: str) -> None:
        """
        Add a job to the processing queue.
        
        Args:
            job_id: The unique identifier of the job to process
        """
        await self._queue.put(job_id)
        logger.info("Job %s enqueued (queue size: %d)", job_id, self._queue.qsize())

    async def _process_loop(self) -> None:
        """
        Main processing loop that runs indefinitely.
        
        Continuously pulls job IDs from the queue and processes them.
        Errors during individual job processing are caught and logged,
        allowing the loop to continue with subsequent jobs.
        """
        while True:
            # Block until a job is available
            job_id = await self._queue.get()
            try:
                await self._process_job(job_id)
            except Exception:
                # Log but don't crash - continue processing other jobs
                logger.exception("Unexpected error processing job %s", job_id)
            finally:
                # Signal that this queue item has been processed
                self._queue.task_done()

    async def _process_job(self, job_id: str) -> None:
        """
        Process a single extraction job.
        
        This method:
        1. Retrieves job details from the database
        2. Updates status to 'processing'
        3. Runs the extraction pipeline in a thread pool
        4. Updates progress as pages are processed
        5. Saves results and updates final status
        
        Args:
            job_id: The unique identifier of the job to process
        """
        # Fetch job details from database
        job = await self._job_store.get_job(job_id)
        if job is None:
            logger.warning("Job %s not found, skipping", job_id)
            return

        logger.info("Processing job %s (%s)", job_id, job["filename"])
        await self._job_store.update_status(job_id, "processing")

        # Create a dedicated output directory for this job
        output_dir = self._output_base_dir / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        loop = asyncio.get_running_loop()

        def progress_callback(current_page: int, total_pages: int) -> None:
            """
            Bridge synchronous pipeline callbacks to async database updates.
            
            The extraction pipeline runs in a thread and calls this synchronously.
            We use run_coroutine_threadsafe to schedule the async database update
            on the main event loop without blocking the pipeline.
            """
            asyncio.run_coroutine_threadsafe(
                self._job_store.update_progress(job_id, current_page, total_pages),
                loop,
            )

        try:
            # Run the CPU-intensive pipeline in a thread pool to avoid
            # blocking the event loop and other async operations
            result = await asyncio.to_thread(
                run_pipeline,
                input_file=job["upload_path"],
                output_dir=str(output_dir),
                extractor=self._extractor,
                progress_callback=progress_callback,
            )

            # Construct the path to the result JSON file
            # The pipeline writes results as {original_name}_extracted.json
            result_filename = Path(job["upload_path"]).stem + "_extracted.json"
            result_path = output_dir / result_filename

            # Mark job as completed with final results
            await self._job_store.update_status(
                job_id,
                "completed",
                result_path=str(result_path),
                current_page=result["total_pages"],
                total_pages=result["total_pages"],
                total_components=result["total_components"],
            )
            logger.info("Job %s completed: %d components", job_id, result["total_components"])

        except Exception as e:
            # Mark job as failed and store the error message
            logger.exception("Job %s failed", job_id)
            # Clean up the output directory since the job failed
            shutil.rmtree(output_dir, ignore_errors=True)
            await self._job_store.update_status(
                job_id,
                "failed",
                error=str(e),
            )

    @staticmethod
    def cleanup_job_files(upload_path: str | None, result_path: str | None) -> None:
        """
        Remove upload and result files/directories for a job.
        
        This is called after a job result has been delivered or when
        cleaning up old jobs. It handles both individual files and
        directories, and attempts to remove empty parent directories.
        
        Args:
            upload_path: Path to the uploaded file (or None)
            result_path: Path to the result file/directory (or None)
        """
        for path_str in (upload_path, result_path):
            if path_str is None:
                continue
            
            path = Path(path_str)
            
            if path.is_file():
                # Remove the file
                path.unlink(missing_ok=True)
                
                # Try to remove the parent directory if it's now empty
                # (job-specific directories like uploads/{uuid}/)
                parent = path.parent
                try:
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                except OSError:
                    # Directory not empty or permission error - ignore
                    pass
                    
            elif path.is_dir():
                # Recursively remove the entire directory
                shutil.rmtree(path, ignore_errors=True)
